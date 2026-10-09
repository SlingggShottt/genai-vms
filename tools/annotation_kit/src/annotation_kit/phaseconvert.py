"""Label Studio export of the phase project -> `phase_labels.jsonl` (`phase_labels.v1`).

This is the export the caption/VQA kit reads (`annotation-kit tasks`), so its shape is the frozen
contract between the phase annotation kit (P3-D5) and the caption/VQA kit (P3-J6): one
`PhaseLabelClip` per line, phases in seconds from the start of the clip, the cut clips' uris.

Per task: the latest non-cancelled annotation. It becomes a line only if it is usable, has at
least one phase, and the phases are valid: in the canonical order, each at most once, not
overlapping. Everything else is skipped and counted by reason, so a lost clip is visible. Annotators
drag boundaries by hand, so a phase that starts up to three frames before the previous one ends is
snapped to touch it rather than thrown away; more than that is a real overlap.

Frames are Label Studio's: counted from 1 (frame 1 is the first instant of the clip) and a range's
`end` is its last frame, included. A range `[s, e]` at `fps` frames per second therefore covers
`(s - 1) / fps` to `e / fps` seconds. The rate is the one in the task (`timeline_fps`: phases are
marked at a coarser rate than the clips' 30 fps so that a clip fits the timeline on screen), unless
one is given.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from annotation_kit.labelconfig import USABLE, USABLE_NO
from annotation_kit.phaseconfig import EVENT_TYPE, FRAMERATE, PHASE, PRIMARY_VIEW
from annotation_kit.phases import PHASES
from annotation_kit.schema import ClipView, PhaseLabelClip, PhaseSpan

SNAP_FRAMES = 3  # at 30 fps; at a coarser rate, one labelling frame
CLIP_FPS = 30
MIN_PHASE_S = 0.1  # shorter is a stray click, not a phase
SKIP_REASONS = (
    "no_annotation",
    "cancelled",
    "unusable",
    "no_phases",
    "bad_range",
    "repeated_phase",
    "out_of_order",
    "overlap",
)
_EPS = 1e-9
_REQUIRED = ("candidate_id", "source_video", "event_type", "primary_view", "clips")


@dataclass
class PhaseConverted:
    clips: list[PhaseLabelClip] = field(default_factory=list)
    skipped: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    snapped: int = 0  # boundaries nudged to touch their neighbour

    @property
    def tasks(self) -> int:
        return len(self.clips) + sum(len(keys) for keys in self.skipped.values())


class _Skip(Exception):  # noqa: N818 - control flow inside this module, not an error type
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _read_result(
    result: Sequence[Mapping[str, Any]],
) -> tuple[list[tuple[str, int, int]], dict[str, str]]:
    """Marked ranges `(phase, start_frame, end_frame)` and `{control: chosen}` from one result."""
    marked: list[tuple[str, int, int]] = []
    choices: dict[str, str] = {}
    for item in result:
        value = item.get("value") or {}
        name = item.get("from_name")
        if item.get("type") == "timelinelabels" and name == PHASE:
            labels = value.get("timelinelabels") or []
            for label in labels:
                for span in value.get("ranges") or []:
                    marked.append((str(label), int(span["start"]), int(span["end"])))
        elif item.get("type") == "choices" and isinstance(name, str) and value.get("choices"):
            choices[name] = value["choices"][0]
    return marked, choices


def _spans(
    marked: Sequence[tuple[str, int, int]], fps: int, duration: float | None
) -> tuple[list[PhaseSpan], int]:
    if not marked:
        raise _Skip("no_phases")
    if any(
        start < 1 or end < start or (end - start + 1) / fps < MIN_PHASE_S
        for _p, start, end in marked
    ):
        raise _Skip("bad_range")
    if len({phase for phase, _s, _e in marked}) != len(marked):
        raise _Skip("repeated_phase")
    ordered = sorted(marked, key=lambda m: (m[1], m[2]))
    if [PHASES.index(p) for p, _s, _e in ordered] != sorted(
        PHASES.index(p) for p, _s, _e in ordered
    ):
        raise _Skip("out_of_order")
    snapped = 0
    tolerance = max(SNAP_FRAMES / CLIP_FPS, 1 / fps) + _EPS
    fixed: list[list[Any]] = [[p, (s - 1) / fps, e / fps] for p, s, e in ordered]  # seconds
    for before, after in zip(fixed, fixed[1:], strict=False):
        overlap = before[2] - after[1]
        if overlap > tolerance:
            raise _Skip("overlap")
        if overlap > _EPS:
            after[1] = before[2]
            snapped += 1
    spans: list[PhaseSpan] = []
    for phase, start_s, end_s in fixed:
        if duration is not None:
            if start_s >= duration:
                continue  # marked past the end of the clip
            end_s = min(end_s, duration)
        spans.append(PhaseSpan(phase=phase, start_s=start_s, end_s=end_s))
    if not spans:
        raise _Skip("no_phases")
    return spans, snapped


def convert_phases(
    export: Sequence[Mapping[str, Any]], *, fps: int | None = None
) -> PhaseConverted:
    out = PhaseConverted()
    for item in export:
        data = item.get("data") or {}
        missing = [k for k in _REQUIRED if k not in data]
        if missing:
            raise ValueError(
                f"a task that is not a phase task (missing {missing}): {str(data)[:120]}"
            )
        key = str(data["candidate_id"])
        try:
            annotations = item.get("annotations") or []
            if not annotations:
                raise _Skip("no_annotation")
            finished = [a for a in annotations if not a.get("was_cancelled") and a.get("result")]
            if not finished:
                raise _Skip("cancelled")
            latest = max(
                finished, key=lambda a: (str(a.get("updated_at") or ""), int(a.get("id") or 0))
            )
            marked, choices = _read_result(latest["result"])
            if choices.get(USABLE) == USABLE_NO:
                raise _Skip("unusable")
            rate = fps or int(data.get("timeline_fps") or FRAMERATE)
            spans, snapped = _spans(marked, rate, data.get("duration_s"))
        except _Skip as skip:
            out.skipped[skip.reason].append(key)
            continue
        clips = [ClipView(camera=c["camera"], video_uri=c["video_uri"]) for c in data["clips"]]
        cameras = {c.camera for c in clips}
        primary = choices.get(PRIMARY_VIEW)
        out.snapped += snapped
        out.clips.append(
            PhaseLabelClip(
                clip_id=key,
                source_video=data["source_video"],
                event_type=choices.get(EVENT_TYPE) or data["event_type"],
                primary_view=primary if primary in cameras else data["primary_view"],
                views=clips,
                phases=spans,
                annotator=_annotator(latest),
            )
        )
    return out


def _annotator(annotation: Mapping[str, Any]) -> str | None:
    by = annotation.get("completed_by")
    if isinstance(by, Mapping):
        by = by.get("email") or by.get("id")
    return None if by is None else str(by)


def write_phase_labels(clips: Sequence[PhaseLabelClip], path: str | Path) -> int:
    with open(path, "w", encoding="utf-8") as handle:
        for clip in clips:
            handle.write(clip.model_dump_json() + "\n")
    return len(clips)


def read_export(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: a Label Studio export is a JSON list of tasks")
    return data


def summarise(converted: PhaseConverted) -> str:
    lines = [f"{len(converted.clips)} of {converted.tasks} tasks became phase labels."]
    if converted.skipped:
        lines.append(
            "Skipped: " + ", ".join(f"{len(k)} {r}" for r, k in converted.skipped.items() if k)
        )
    if converted.snapped:
        lines.append(f"{converted.snapped} phase boundaries were snapped to touch their neighbour.")
    return "\n".join(lines) + "\n"
