"""Phase labels made from a dataset's own crime span, for clips nobody marked by hand.

UCF-Crime's test videos come with one start and one end time for "the crime". That is not the five
stages the project needs (it says nothing of where the lead-up begins), but it does split a clip in
three: before the span, the span, after it. Used as `baseline`, `action` and `aftermath` it gives a
weak label with no human time. Weak, because:

- it can only ever have those three stages, never `precursor` or `escalation`;
- the spans are rough: on the first five clips compared with a person's marks two disagreed (one
  span covered title cards the video was edited to include, one was much shorter than the visible
  act);
- it is not a person's judgement, so **it must never be counted with, or scored against, the clips
  people marked**. Every label made here carries `WEAK_ANNOTATOR` in `annotator` so that the two
  can be told apart, and the output is a separate file.

The labelling grid is a second (`phaseconfig.FRAMERATE`), so a stage shorter than a second is left
out, as a person's mark of that length would be.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from annotation_kit.candidates import PhaseCandidate, clip_uri
from annotation_kit.schema import ClipView, PhaseLabelClip, PhaseSpan
from annotation_kit.ucf import Span

WEAK_ANNOTATOR = "dataset-span:ucf-crime"
MIN_STAGE_S = 1.0


class WeakLabelError(ValueError):
    pass


def span_in_clip(
    spans: Sequence[Span], window_start_s: float, duration_s: float
) -> tuple[float, float] | None:
    """The crime's start and end in seconds into the clip: from the first span's start to the last
    span's end (as `ucf.select_candidates` does), clipped to the clip. None if none of it is in the
    clip."""
    inside = [
        (max(0.0, s.start_s - window_start_s), min(duration_s, s.end_s - window_start_s))
        for s in spans
        if s.end_s - window_start_s > 0 and s.start_s - window_start_s < duration_s
    ]
    if not inside:
        return None
    return min(a for a, _ in inside), max(b for _, b in inside)


def phases_from_span(start_s: float, end_s: float, duration_s: float) -> list[PhaseSpan]:
    """`baseline` before the span, `action` for it, `aftermath` after it; a stage under a second is
    left out. An empty list when the span itself is under a second."""
    start_s, end_s = max(0.0, start_s), min(duration_s, end_s)
    if end_s - start_s < MIN_STAGE_S:
        return []
    out: list[PhaseSpan] = []
    if start_s >= MIN_STAGE_S:
        out.append(PhaseSpan(phase="baseline", start_s=0.0, end_s=start_s))
    out.append(PhaseSpan(phase="action", start_s=start_s, end_s=end_s))
    if duration_s - end_s >= MIN_STAGE_S:
        out.append(PhaseSpan(phase="aftermath", start_s=end_s, end_s=duration_s))
    return out


def weak_label(
    candidate: PhaseCandidate, spans: Sequence[Span], *, clip_prefix: str
) -> PhaseLabelClip | None:
    """The label for one UCF-Crime candidate, or None if the crime is not in its window."""
    if candidate.dataset != "ucf_crime":
        raise WeakLabelError(f"{candidate.candidate_id}: spans are only known for UCF-Crime")
    primary = next(v for v in candidate.views if v.camera == candidate.primary_view)
    found = span_in_clip(spans, primary.start_s, candidate.duration_s)
    if found is None:
        return None
    phases = phases_from_span(*found, candidate.duration_s)
    if not phases:
        return None
    return PhaseLabelClip(
        clip_id=candidate.candidate_id,
        source_video=candidate.source_video,
        event_type=candidate.event_type,
        primary_view=candidate.primary_view,
        views=[
            ClipView(camera=v.camera, video_uri=clip_uri(clip_prefix, candidate, v))
            for v in candidate.views
        ],
        phases=phases,
        annotator=WEAK_ANNOTATOR,
    )


def skipped_in(export: Sequence[Mapping[str, Any]]) -> set[str]:
    """Candidate ids of the tasks somebody opened but left without a mark: every annotation of
    theirs was a skip, or had no result."""
    out: set[str] = set()
    for item in export:
        annotations = item.get("annotations") or []
        if annotations and not any(
            a.get("result") and not a.get("was_cancelled") for a in annotations
        ):
            out.add(str((item.get("data") or {})["candidate_id"]))
    return out


def video_file(candidate: PhaseCandidate) -> str:
    """The name the annotation file knows the candidate's video by: `Abuse028_x264.mp4`."""
    return candidate.candidate_id.split(":", 1)[-1] + ".mp4"


def write_weak_labels(clips: Collection[PhaseLabelClip], path: str | Path) -> int:
    with open(path, "w", encoding="utf-8") as handle:
        for clip in clips:
            handle.write(clip.model_dump_json() + "\n")
    return len(clips)
