"""One annotator's self-contained package: their clips, tasks, labelling forms and scripts.

The annotators work on their own machines, so everything they need is in one folder:

    annotation-<name>/
      clips/<clip>/<camera>.mp4   the cut clips of this annotator's batch, and nothing else
      tasks/tasks_<n>views.json   one file per number of views (each is a project)
      config/phase_labelling_<n>views.xml
      ls_setup.py                 creates their projects in Label Studio and exports their work
      start.sh  export.sh         start Label Studio and set up; write `export-<name>.json`
      README.md  QUICKSTART.md  GUIDELINE.md

`start.sh` installs Label Studio into a virtualenv on the first run, starts it with local-file
serving rooted in this folder (so the clips are played from disk, nothing is uploaded), and creates
the projects. Nothing here talks to anything but the annotator's own Label Studio, apart from the
one-off `pip install`.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from annotation_kit.candidates import PhaseCandidate, clip_relpath
from annotation_kit.phaseconfig import config_filename
from annotation_kit.phasetasks import phase_tasks
from annotation_kit.tasks import dump_json

DEFAULT_PORT = 8090
CLIP_PREFIX = "local://clips"
SERVED_FROM = "/data/local-files/?d=clips/"  # Label Studio's local-files URL for clips/<...>


class PackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class PackageReport:
    folder: Path
    clips: int
    files: int
    bytes: int
    tasks: dict[int, int]  # tasks by number of views


START_SH = """#!/usr/bin/env bash
# Starts Label Studio for __NAME__ and sets up their projects. Ctrl+C stops it.
# Safe to run again: nothing is created twice, and what has been annotated is kept.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
PORT="${PORT:-__PORT__}"

if [ -z "${LS_BIN:-}" ]; then
  if [ ! -x .venv/bin/label-studio ]; then
    echo "First run: installing Label Studio (a few minutes, needs the internet)..."
    python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet label-studio
  fi
  LS_BIN=.venv/bin/label-studio
  PY=.venv/bin/python
else
  PY="${PYTHON:-python3}"
fi

if [ ! -f .account ]; then
  SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(9))')"
  printf 'annotator@annotation.local\\n%s\\n' "$SECRET" > .account
  chmod 600 .account
fi
EMAIL="$(sed -n 1p .account)"
PASSWORD="$(sed -n 2p .account)"

export LABEL_STUDIO_BASE_DATA_DIR="$HERE/data"
export LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true
export LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT="$HERE"
export LABEL_STUDIO_DISABLE_SIGNUP_WITHOUT_LINK=true
export LABEL_STUDIO_COLLECT_ANALYTICS=false
export LABEL_STUDIO_SENTRY_DSN=""            # no error reports to the vendor, from the server
export LABEL_STUDIO_FRONTEND_SENTRY_DSN=""   # or from the page
export DJANGO_DB=sqlite

# --name=value, because a generated password can begin with "-", which is read as an option
"$LS_BIN" start --port "$PORT" --no-browser --username="$EMAIL" --password="$PASSWORD" \\
  > label-studio.log 2>&1 &
LS_PID=$!
trap 'kill "$LS_PID" 2>/dev/null || true' EXIT INT TERM

echo -n "Waiting for Label Studio"
for _ in $(seq 1 120); do
  if curl -fsS "http://localhost:$PORT/health" > /dev/null 2>&1; then break; fi
  if ! kill -0 "$LS_PID" 2>/dev/null; then
    echo; echo "Label Studio stopped; see label-studio.log"; exit 1
  fi
  echo -n "."; sleep 2
done
echo

LABEL_STUDIO_EMAIL="$EMAIL" LABEL_STUDIO_PASSWORD="$PASSWORD" "$PY" ls_setup.py \\
  --url "http://localhost:$PORT" --annotator "__NAME__" --config-dir config \\
  --tasks-dir tasks --media-root "$HERE/clips" --token-file .token

echo
echo "Open  http://localhost:$PORT"
echo "Email    $EMAIL"
echo "Password $PASSWORD"
echo "(read QUICKSTART.md first; Ctrl+C here to stop)"
wait "$LS_PID"
"""

EXPORT_SH = """#!/usr/bin/env bash
# Writes everything __NAME__ has annotated to export-__NAME__.json, to send back.
# Label Studio must be running (./start.sh in another terminal).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-__PORT__}"
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3
"$PY" ls_setup.py --url "http://localhost:$PORT" --annotator "__NAME__" \\
  --export "export-__NAME__.json" --token-file .token
"""

README = """# Phase annotation package for __NAME__

__CLIPS__ clips (__VIEWS__ video files, __SIZE__) to label with the phases of what happens in them.

## What you need

- Linux, macOS or Windows with WSL2 (Ubuntu), with `python3` (3.10 to 3.12) and `python3-venv`
  (on Ubuntu: `sudo apt install python3-venv`), and `curl`.
- About 1 GB of free disk for Label Studio and room for this folder.
- The internet once, for the first start (it installs Label Studio).
- A recent Chrome, Edge or Brave. Firefox and Safari are not tested.

## Start

```bash
cd annotation-__NAME__
./start.sh
```

The first run takes a few minutes. When it prints `Open http://localhost:__PORT__`, open that in the
browser and sign in with the email and password it printed (they are also in `.account`).
Leave the terminal open while you work; Ctrl+C stops Label Studio. Run `./start.sh` again whenever
you come back: your work is kept.

## Annotate

Read `QUICKSTART.md` (five minutes), then `GUIDELINE.md` for the definitions of the phases.

## Send your work back

With Label Studio running, in a second terminal:

```bash
./export.sh
```

That writes `export-__NAME__.json`. Send that one file back, after your first 5 clips (so that
problems show early) and again when you are done.

## If something does not work

- `label-studio.log` in this folder has Label Studio's own messages.
- `./start.sh` stops with "Label Studio stopped": usually the port is taken. Try
  `PORT=8091 ./start.sh` (and `PORT=8091 ./export.sh`).
- Videos do not play: use Chrome, Edge or Brave.
"""


def _size(n: float) -> str:
    for unit in ("bytes", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _served(uri: str) -> str:
    return SERVED_FROM + uri[len(CLIP_PREFIX) + 1 :] if uri.startswith(CLIP_PREFIX + "/") else uri


def build_package(
    annotator: str,
    candidates: Sequence[PhaseCandidate],
    *,
    clips_dir: Path,
    config_dir: Path,
    ls_setup: Path,
    docs: dict[str, Path],
    out_dir: Path,
    port: int = DEFAULT_PORT,
    link: bool = False,
    replace: bool = False,
) -> PackageReport:
    """Build `out_dir/annotation-<annotator>`. `docs` maps a file name in the package to its
    source. `link` hard-links the clips instead of copying them (same filesystem: instant, and no
    extra disk)."""
    folder = out_dir / f"annotation-{annotator}"
    wanted = [
        (view, clips_dir / clip_relpath(candidate, view))
        for candidate in candidates
        for view in candidate.views
    ]
    missing = [
        str(path) for _view, path in wanted if not path.is_file() or path.stat().st_size == 0
    ]
    if missing:
        raise PackageError(
            f"{len(missing)} of {len(wanted)} cut clips are missing or empty, e.g. {missing[0]}"
        )
    if folder.exists():
        if not replace:
            raise PackageError(f"{folder} exists (use --replace to rebuild it)")
        shutil.rmtree(folder)

    grouped = phase_tasks(candidates, clip_prefix=CLIP_PREFIX, resolve_uri=_served)
    (folder / "tasks").mkdir(parents=True)
    (folder / "config").mkdir()
    for views, tasks in grouped.items():
        suffix = "s" if views > 1 else ""
        dump_json(tasks, folder / "tasks" / f"tasks_{views}view{suffix}.json")
        shutil.copy2(
            config_dir / config_filename(views), folder / "config" / config_filename(views)
        )

    total = 0
    for candidate in candidates:
        for view in candidate.views:
            source = clips_dir / clip_relpath(candidate, view)
            target = folder / "clips" / clip_relpath(candidate, view)
            target.parent.mkdir(parents=True, exist_ok=True)
            if link:
                os.link(source, target)
            else:
                shutil.copy2(source, target)
            total += target.stat().st_size

    shutil.copy2(ls_setup, folder / "ls_setup.py")
    fill = {"__NAME__": annotator, "__PORT__": str(port)}
    for name, template in (("start.sh", START_SH), ("export.sh", EXPORT_SH)):
        text = template
        for key, value in fill.items():
            text = text.replace(key, value)
        (folder / name).write_text(text, encoding="utf-8")
        (folder / name).chmod(0o755)
    readme = README
    for key, value in {
        **fill,
        "__CLIPS__": str(len(candidates)),
        "__VIEWS__": str(len(wanted)),
        "__SIZE__": _size(total),
    }.items():
        readme = readme.replace(key, value)
    (folder / "README.md").write_text(readme, encoding="utf-8")
    for name, source in docs.items():
        shutil.copy2(source, folder / name)

    files = sum(1 for p in folder.rglob("*") if p.is_file())
    return PackageReport(
        folder=folder,
        clips=len(candidates),
        files=files,
        bytes=total,
        tasks={views: len(tasks) for views, tasks in grouped.items()},
    )
