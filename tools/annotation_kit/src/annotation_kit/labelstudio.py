"""An annotator's phase-labelling projects, put into a running Label Studio from the kit's files.

One project per annotator and number of views (a Label Studio labelling form is fixed, and the
phase form has one video per view), each with the matching config and tasks. Safe to run twice:
a project that already exists by title is left alone, and its tasks are not imported again.

Only the standard library and no import from the rest of the kit, so this one file runs wherever
Label Studio does (it is shipped as `ls_setup.py` in each annotator's package):

    python ls_setup.py --annotator kuldeep --tasks-dir tasks --media-root clips

It signs in with a personal access token (`LABEL_STUDIO_TOKEN`) or, for a Label Studio just started
with an account, that account's `LABEL_STUDIO_EMAIL` and `LABEL_STUDIO_PASSWORD`; never on the
command line.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_TASKS_FILE = re.compile(r"^tasks_(\d+)views?\.json$")

Transport = Callable[[str, str, Any], Any]


class LabelStudioError(RuntimeError):
    pass


def config_filename(views: int) -> str:
    """The labelling config for tasks with this many views (as `phaseconfig.config_filename`; a test
    keeps the two the same, so that this file needs nothing else from the kit)."""
    return f"phase_labelling_{views}view{'s' if views > 1 else ''}.xml"


def is_personal_token(token: str) -> bool:
    """A personal access token (Label Studio 1.22+: Account & Settings > Personal Access Token) is a
    JWT, three dot-separated parts starting `ey`; an older API token is a plain hex string."""
    return token.startswith("ey") and token.count(".") == 2


def http_transport(base_url: str, token: str, *, timeout: float = 120.0) -> Transport:
    """`call(method, path, payload) -> parsed JSON` against a real Label Studio. A personal access
    token is exchanged for a short-lived access token on first use."""
    session: dict[str, str] = {}

    def send(method: str, path: str, payload: Any, authorization: str | None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if authorization:
            headers["Authorization"] = authorization
        request = urllib.request.Request(  # noqa: S310 - the URL is the operator's own Label Studio
            base_url.rstrip("/") + path, data=body, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise LabelStudioError(f"{method} {path}: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise LabelStudioError(f"{method} {path}: {exc.reason}") from exc
        return json.loads(raw) if raw else None

    def call(method: str, path: str, payload: Any = None) -> Any:
        if "authorization" not in session:
            if is_personal_token(token):
                access = send("POST", "/api/token/refresh/", {"refresh": token}, None)["access"]
                session["authorization"] = f"Bearer {access}"
            else:
                session["authorization"] = f"Token {token}"
        return send(method, path, payload, session["authorization"])

    return call


def personal_token(base_url: str, email: str, password: str, *, timeout: float = 60.0) -> str:
    """Sign in as `email` and create a personal access token (what the API accepts on 1.22+, where
    the old per-user token is switched off). The sign-in is the web form's: a CSRF cookie, then a
    post."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    root = base_url.rstrip("/")

    def csrf() -> str:
        return next((c.value for c in jar if c.name == "csrftoken"), "")

    def post(path: str, fields: dict[str, str] | None) -> bytes:
        data = urllib.parse.urlencode(fields).encode() if fields is not None else b""
        request = urllib.request.Request(  # noqa: S310 - the operator's own Label Studio
            root + path,
            data=data,
            method="POST",
            headers={"X-CSRFToken": csrf(), "Referer": root + "/"},
        )
        with opener.open(request, timeout=timeout) as response:
            return response.read()

    try:
        opener.open(root + "/user/login/", timeout=timeout).read()  # sets the CSRF cookie
        page = post(
            "/user/login/",
            {"email": email, "password": password, "csrfmiddlewaretoken": csrf()},
        )
        if b'name="password"' in page:  # the form again: the sign-in was refused
            raise LabelStudioError("sign-in refused: wrong email or password")
        token = json.loads(post("/api/token/", None)).get("token")
    except urllib.error.HTTPError as exc:
        if exc.code == 409:  # one token per account, and Label Studio will not show it again
            raise LabelStudioError(
                "this account already has a personal access token, which cannot be read back: "
                "give it as LABEL_STUDIO_TOKEN (or revoke it under Account & Settings)"
            ) from exc
        raise LabelStudioError(f"sign-in failed: {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise LabelStudioError(f"sign-in failed: {exc.reason}") from exc
    if not token:
        raise LabelStudioError("Label Studio did not give a personal access token")
    return str(token)


def project_title(annotator: str, views: int) -> str:
    return f"{annotator} - {views} view{'s' if views > 1 else ''}"


def tasks_by_views(tasks_dir: Path) -> dict[int, Path]:
    """{number of views: tasks file} for the `tasks_<n>view(s).json` files in a folder."""
    found = {}
    for path in sorted(tasks_dir.iterdir()):
        match = _TASKS_FILE.match(path.name)
        if match:
            found[int(match.group(1))] = path
    return found


def _existing_projects(call: Transport) -> dict[str, dict]:
    page = call("GET", "/api/projects?page_size=500", None)
    results = page["results"] if isinstance(page, dict) else page
    return {p["title"]: p for p in results}


def _ensure_media_storage(call: Transport, project_id: int, media_root: Path) -> bool:
    """Label Studio serves a local file only to a project with a Local Files storage covering its
    folder, so give each project one for the clips (nothing is synced from it). True if created."""
    path = str(media_root.resolve())
    found = call("GET", f"/api/storages/localfiles?project={project_id}", None)
    if any(storage.get("path") == path for storage in found):
        return False
    call(
        "POST",
        "/api/storages/localfiles",
        {"project": project_id, "title": "cut clips", "path": path, "use_blob_urls": False},
    )
    return True


def setup_annotator(
    call: Transport,
    *,
    annotator: str,
    config_dir: Path,
    tasks_dir: Path,
    media_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Create (or find) the annotator's projects and import their tasks. With `media_root` (the
    folder of cut clips, which Label Studio must be set up to serve) each project is also given
    access to it. Returns one dict per project: title, id, tasks in the file, tasks imported now,
    the project's task count and whether the clips storage was added now."""
    files = tasks_by_views(tasks_dir)
    if not files:
        raise LabelStudioError(f"no tasks_<n>views.json files in {tasks_dir}")
    projects = _existing_projects(call)
    report = []
    for views, path in files.items():
        title = project_title(annotator, views)
        config = (config_dir / config_filename(views)).read_text(encoding="utf-8")
        tasks = json.loads(path.read_text(encoding="utf-8"))
        project = projects.get(title)
        created = project is None
        if project is None:
            project = call("POST", "/api/projects", {"title": title, "label_config": config})
        imported = 0
        if created or not project.get("task_number"):
            result = call("POST", f"/api/projects/{project['id']}/import", tasks)
            imported = int(result.get("task_count", 0))
        storage = _ensure_media_storage(call, project["id"], media_root) if media_root else False
        total = call("GET", f"/api/projects/{project['id']}", None).get("task_number")
        report.append(
            {
                "title": title,
                "id": project["id"],
                "created": created,
                "tasks_in_file": len(tasks),
                "imported": imported,
                "tasks_in_project": total,
                "storage_added": storage,
            }
        )
    return report


def export_annotator(call: Transport, annotator: str) -> list[dict[str, Any]]:
    """Every annotated task in the annotator's projects, in the form `phase-convert` reads. Label
    Studio exports one project at a time and the annotator has one per number of views."""
    prefix = f"{annotator} - "
    tasks: list[dict[str, Any]] = []
    for title, project in sorted(_existing_projects(call).items()):
        if title.startswith(prefix):
            path = f"/api/projects/{project['id']}/export?exportType=JSON&download_all_tasks=false"
            tasks += call("GET", path, None)
    return tasks


def _sign_in(url: str, env: Mapping[str, str], token_file: Path | None) -> str:
    """A token from the environment, else from `token_file`, else by signing in with the account
    (and saved to `token_file`: Label Studio gives one token per account and shows it once)."""
    token = env.get("LABEL_STUDIO_TOKEN", "")
    if not token and token_file is not None and token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
    if not token and env.get("LABEL_STUDIO_EMAIL") and env.get("LABEL_STUDIO_PASSWORD"):
        token = personal_token(url, env["LABEL_STUDIO_EMAIL"], env["LABEL_STUDIO_PASSWORD"])
        if token_file is not None:
            token_file.write_text(token, encoding="utf-8")
            token_file.chmod(0o600)
    return token


def run(
    url: str,
    annotator: str,
    config_dir: Path,
    tasks_dir: Path | None,
    media_root: Path | None,
    *,
    export_to: Path | None = None,
    token_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Set an annotator up and print one line per project, or (`export_to`) write their annotations
    to a file. 0 on success, 1 on a Label Studio error, 2 when something needed is not given."""
    env = os.environ if environ is None else environ
    try:
        token = _sign_in(url, env, token_file)
        if not token:
            print(
                "set LABEL_STUDIO_TOKEN, or LABEL_STUDIO_EMAIL and LABEL_STUDIO_PASSWORD",
                file=sys.stderr,
            )
            return 2
        call = http_transport(url, token)
        if export_to is not None:
            tasks = export_annotator(call, annotator)
            export_to.write_text(json.dumps(tasks, indent=1), encoding="utf-8")
            done = sum(1 for t in tasks if t.get("annotations"))
            print(f"{done} annotated tasks written to {export_to}")
            return 0
        if tasks_dir is None:
            print("--tasks-dir is needed to set projects up", file=sys.stderr)
            return 2
        report = setup_annotator(
            call,
            annotator=annotator,
            config_dir=config_dir,
            tasks_dir=tasks_dir,
            media_root=media_root,
        )
    except LabelStudioError as exc:
        print(f"label studio: {exc}", file=sys.stderr)
        return 1
    for row in report:
        what = "created" if row["created"] else "found"
        print(
            f"{row['title']}: {what} (project {row['id']}), imported {row['imported']} of "
            f"{row['tasks_in_file']} tasks, {row['tasks_in_project']} in the project"
        )
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--annotator", required=True)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--tasks-dir", help="the folder phase-tasks wrote")
    parser.add_argument(
        "--media-root",
        help="the folder of cut clips, if Label Studio serves it (LOCAL_FILES_DOCUMENT_ROOT)",
    )
    parser.add_argument(
        "--export", metavar="FILE", help="write the annotator's annotations to FILE instead"
    )
    parser.add_argument(
        "--token-file", help="read the access token from here, or sign in and save it here"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_arguments(parser)
    args = parser.parse_args(argv)
    return run(
        args.url,
        args.annotator,
        Path(args.config_dir),
        Path(args.tasks_dir) if args.tasks_dir else None,
        Path(args.media_root) if args.media_root else None,
        export_to=Path(args.export) if args.export else None,
        token_file=Path(args.token_file) if args.token_file else None,
    )


if __name__ == "__main__":
    sys.exit(main())
