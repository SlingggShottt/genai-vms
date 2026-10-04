"""Candidates -> Label Studio tasks for phase labelling, and the commands that cut the clips.

The video an annotator watches is a *cut clip*, not the source: every view is cut to the same
window (see `candidates.py`), stored under a prefix, and the task points at those. The task carries
everything the converter needs to rebuild a `phase_labels.v1` line, so an export is self-contained.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from annotation_kit.candidates import PhaseCandidate, clip_relpath, clip_uri, cut_command
from annotation_kit.phaseconfig import video_name

UriResolver = Callable[[str], str]


def _identity(uri: str) -> str:
    return uri


def phase_task(
    candidate: PhaseCandidate, *, clip_prefix: str, resolve_uri: UriResolver = _identity
) -> dict[str, Any]:
    """One Label Studio import item: `video`, `video_2`, ... are the views, primary first."""
    views = sorted(candidate.views, key=lambda v: (v.camera != candidate.primary_view, v.camera))
    data: dict[str, Any] = {
        "candidate_id": candidate.candidate_id,
        "dataset": candidate.dataset,
        "source_video": candidate.source_video,
        "event_type": candidate.event_type,
        "activity": candidate.activity or "",
        "primary_view": candidate.primary_view,
        "duration_s": round(candidate.duration_s, 3),
        "views": [v.camera for v in views],
        "clips": [
            {"camera": v.camera, "video_uri": clip_uri(clip_prefix, candidate, v)} for v in views
        ],
    }
    for index, view in enumerate(views):
        data[video_name(index)] = resolve_uri(clip_uri(clip_prefix, candidate, view))
    return {"data": data}


def phase_tasks(
    candidates: Iterable[PhaseCandidate], *, clip_prefix: str, resolve_uri: UriResolver = _identity
) -> dict[int, list[dict[str, Any]]]:
    """Tasks grouped by how many views they have: each count is its own Label Studio project."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for candidate in candidates:
        task = phase_task(candidate, clip_prefix=clip_prefix, resolve_uri=resolve_uri)
        grouped.setdefault(len(candidate.views), []).append(task)
    return dict(sorted(grouped.items()))


def cut_plan(
    candidates: Iterable[PhaseCandidate],
    out_dir: str | Path,
    *,
    resolve_source: UriResolver | None = None,
) -> list[tuple[Path, list[str]]]:
    """`(output path, ffmpeg argv)` for every view of every candidate."""
    plan: list[tuple[Path, list[str]]] = []
    for candidate in candidates:
        for view in candidate.views:
            out = Path(out_dir) / clip_relpath(candidate, view)
            plan.append((out, cut_command(view, out, resolve_source=resolve_source)))
    return plan


def cut_script(plan: Sequence[tuple[Path, Sequence[str]]]) -> str:
    """A shell script that makes the folders and runs every cut, skipping what already exists."""
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    for out, argv in plan:
        lines.append(f"mkdir -p {shlex.quote(str(out.parent))}")
        lines.append(f"[ -s {shlex.quote(str(out))} ] || {shlex.join(argv)}")
    return "\n".join(lines) + "\n"


def run_cuts(
    plan: Sequence[tuple[Path, Sequence[str]]],
    *,
    run: Callable[..., Any] = subprocess.run,
) -> Mapping[str, int]:
    """Run the cuts that are not already there. Returns how many were cut, kept and failed."""
    done = {"cut": 0, "kept": 0, "failed": 0}
    for out, argv in plan:
        if out.exists() and out.stat().st_size > 0:
            done["kept"] += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        result = run(list(argv), check=False)  # noqa: S603 - argv built by cut_command
        if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
            done["cut"] += 1
        else:
            out.unlink(missing_ok=True)
            done["failed"] += 1
    return done
