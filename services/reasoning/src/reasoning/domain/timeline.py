"""Phase timelines (design §8.2): turning a model's per-frame stage labels into contiguous,
ordered spans, and the rule-based timeline used when the model's answer is unusable. Pure."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from vms_common.contracts.reasoning import PHASES, PhaseName, PhaseSpan

ORDER = {p: i for i, p in enumerate(PHASES)}

PHASE_MEANING: dict[str, str] = {
    "baseline": "ordinary scene before anything related to the incident",
    "precursor": "first signs: approaching, lingering, looking around",
    "escalation": "the build-up; the incident is about to happen",
    "action": "the incident itself is happening",
    "aftermath": "afterwards: people leaving, reacting, or the scene returning to normal",
}


class FrameLabels(BaseModel):
    """One stage name per frame, in frame order (an array of plain strings is the shape small
    models get right most often)."""

    phases: list[PhaseName]


def spans_from_labels(
    labels: list[PhaseName],
    frame_times: list[datetime],
    *,
    window_start: datetime,
    window_end: datetime,
    source: str,
) -> list[PhaseSpan] | None:
    """Spans from per-frame labels, or None when the labels cannot be trusted.

    Stages never run backwards, so a label earlier than one already seen is lifted to it.
    Boundaries sit halfway between the last frame of one stage and the first of the next. A
    labelling that puts every frame in one stage tells us nothing about boundaries and is
    rejected, as is one that does not cover the frames.
    """
    if len(labels) != len(frame_times):
        return None
    phases: list[PhaseName] = []
    top = 0
    for label in labels:
        top = max(top, ORDER[label])
        phases.append(PHASES[top])
    if len(set(phases)) < 2:
        return None

    spans: list[PhaseSpan] = []
    start = window_start
    for i, phase in enumerate(phases):
        last = i == len(phases) - 1
        if not last and phases[i + 1] == phase:
            continue
        end = window_end if last else frame_times[i] + (frame_times[i + 1] - frame_times[i]) / 2
        spans.append(PhaseSpan(phase=phase, start=start, end=end, source=source))
        start = end
    return spans


def rule_spans(
    *,
    window_start: datetime,
    window_end: datetime,
    event_start: datetime,
    event_end: datetime,
    source: str = "rules",
) -> list[PhaseSpan]:
    """A timeline from the detector's own timing: the flagged span is the action, a lead-in
    before it is escalation then precursor, the rest before is baseline, after it is aftermath.
    Empty phases are dropped (phases may be empty, §8.2)."""
    lead = (event_start - window_start).total_seconds()
    cuts = [
        ("baseline", window_start, event_start - _secs(min(lead, 8.0))),
        ("precursor", event_start - _secs(min(lead, 8.0)), event_start - _secs(min(lead, 3.0))),
        ("escalation", event_start - _secs(min(lead, 3.0)), event_start),
        ("action", event_start, max(event_end, event_start)),
        ("aftermath", max(event_end, event_start), window_end),
    ]
    return [
        PhaseSpan(phase=name, start=a, end=b, source=source)  # type: ignore[arg-type]
        for name, a, b in cuts
        if b > a
    ]


def _secs(s: float):
    from datetime import timedelta

    return timedelta(seconds=s)
