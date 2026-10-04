"""Phase-annotated clips -> caption/VQA labelling tasks.

Each phase of each clip, in each camera's view, is one task: PhaVR is trained to caption one phase
in one view and to answer questions about it, so that is the unit a person verifies. A clip with 4
phases seen by 3 cameras makes 12 tasks. A phase with nothing in it is not in the export, so it
makes no task.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from annotation_kit.schema import CaptionVqaTask, PhaseLabelClip

UriResolver = Callable[[str], str]


def _identity(uri: str) -> str:
    return uri


def read_phase_labels(path: str | Path) -> list[PhaseLabelClip]:
    """Read `phase_labels.jsonl`: one clip per line. A bad line says which one."""
    clips: list[PhaseLabelClip] = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                clips.append(PhaseLabelClip.model_validate_json(line))
            except ValueError as error:
                raise ValueError(f"{path}, line {number}: {error}") from error
    return clips


def tasks_from_clips(
    clips: Iterable[PhaseLabelClip], *, resolve_uri: UriResolver = _identity
) -> Iterator[CaptionVqaTask]:
    """Expand every clip into its phase x view tasks, primary view first.

    `resolve_uri` turns a stored `s3://` uri into something Label Studio's player can fetch (a
    presigned or proxied url); the clip's own uri is kept untouched for the model.
    """
    for clip in clips:
        views = sorted(clip.views, key=lambda view: view.camera != clip.primary_view)
        for span in clip.phases:
            for view in views:
                yield CaptionVqaTask(
                    clip_id=clip.clip_id,
                    source_video=clip.source_video,
                    event_type=clip.event_type,
                    view=view.camera,
                    phase=span.phase,
                    start_s=span.start_s,
                    end_s=span.end_s,
                    video_uri=view.video_uri,
                    video=f"{resolve_uri(view.video_uri)}#t={span.start_s:g},{span.end_s:g}",
                )


def to_label_studio_import(tasks: Iterable[CaptionVqaTask]) -> list[dict[str, object]]:
    """Label Studio's import format without drafts: `[{"data": {...}}]`."""
    return [{"data": task.model_dump()} for task in tasks]


def dump_json(payload: object, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
