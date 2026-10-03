"""How much two annotators agree about the phases of the same clips (inter-annotator agreement).

Phase boundaries are judgement calls, so two careful people will not mark exactly the same frames.
The question is whether they mark *about* the same thing, and where they differ. Measured on the
overlap set both annotate (the design uses 20 clips for K and P), matched by `clip_id`:

- per-phase IoU: the intersection over the union of the two annotators' spans for that phase, 0 if
  only one marked it; averaged over the clips where either marked it. Their mean over phases is the
  mIoU (the metric the TG adapter is later scored with, design section 8.3);
- boundary error: the average difference in seconds between their starts and ends, for phases both
  marked;
- presence agreement per phase: whether they agree that the phase happens at all;
- frame-wise agreement and Cohen's kappa over a 0.1 s grid, unmarked time being its own label;
- whether they chose the same primary view and event type.

Low agreement on one phase is a guideline problem, not an annotator problem: fix the definition.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from annotation_kit.phases import PHASES
from annotation_kit.schema import PhaseLabelClip

GRID_S = 0.1
NONE = "none"


def interval_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def _spans(clip: PhaseLabelClip) -> dict[str, tuple[float, float]]:
    return {span.phase: (span.start_s, span.end_s) for span in clip.phases}


def frame_labels(clip: PhaseLabelClip, length_s: float, step: float = GRID_S) -> list[str]:
    """The phase at each grid point of [0, length_s), or `none`."""
    spans = _spans(clip)
    labels: list[str] = []
    for i in range(int(round(length_s / step))):
        t = i * step + step / 2
        labels.append(next((p for p, (s, e) in spans.items() if s <= t < e), NONE))
    return labels


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Agreement beyond chance; None when chance is already total (one label throughout)."""
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    chance = sum((ca[label] / n) * (cb[label] / n) for label in set(ca) | set(cb))
    return None if chance >= 1 else (observed - chance) / (1 - chance)


@dataclass
class Agreement:
    clips: int = 0
    iou_by_phase: dict[str, float | None] = field(default_factory=dict)
    miou: float | None = None
    boundary_error_s: float | None = None
    presence_by_phase: dict[str, float | None] = field(default_factory=dict)
    frame_agreement: float | None = None
    kappa: float | None = None
    primary_view: float | None = None
    event_type: float | None = None
    clip_miou: dict[str, float] = field(default_factory=dict)  # per clip, lowest first

    def as_dict(self) -> dict[str, object]:
        return {
            "clips": self.clips,
            "iou_by_phase": self.iou_by_phase,
            "miou": self.miou,
            "boundary_error_s": self.boundary_error_s,
            "presence_by_phase": self.presence_by_phase,
            "frame_agreement": self.frame_agreement,
            "kappa": self.kappa,
            "primary_view_agreement": self.primary_view,
            "event_type_agreement": self.event_type,
            "least_agreed_clips": dict(list(self.clip_miou.items())[:5]),
        }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def compare(a: Sequence[PhaseLabelClip], b: Sequence[PhaseLabelClip]) -> Agreement:
    """Compare two annotators on the clips both labelled."""
    by_a = {clip.clip_id: clip for clip in a}
    by_b = {clip.clip_id: clip for clip in b}
    shared = sorted(set(by_a) & set(by_b))
    result = Agreement(clips=len(shared))

    ious: dict[str, list[float]] = {phase: [] for phase in PHASES}
    present: dict[str, list[float]] = {phase: [] for phase in PHASES}
    errors: list[float] = []
    grid_a: list[str] = []
    grid_b: list[str] = []
    same_view = same_type = 0
    per_clip: dict[str, float] = {}

    for clip_id in shared:
        ca, cb = by_a[clip_id], by_b[clip_id]
        sa, sb = _spans(ca), _spans(cb)
        clip_ious = []
        for phase in PHASES:
            in_a, in_b = phase in sa, phase in sb
            present[phase].append(float(in_a == in_b))
            if not (in_a or in_b):
                continue
            iou = interval_iou(sa[phase], sb[phase]) if in_a and in_b else 0.0
            ious[phase].append(iou)
            clip_ious.append(iou)
            if in_a and in_b:
                errors += [abs(sa[phase][0] - sb[phase][0]), abs(sa[phase][1] - sb[phase][1])]
        if clip_ious:
            per_clip[clip_id] = sum(clip_ious) / len(clip_ious)
        length = max([e for _s, e in [*sa.values(), *sb.values()]] or [0.0])
        grid_a += frame_labels(ca, length)
        grid_b += frame_labels(cb, length)
        same_view += ca.primary_view == cb.primary_view
        same_type += ca.event_type == cb.event_type

    result.iou_by_phase = {p: _mean(v) for p, v in ious.items()}
    result.miou = _mean([v for v in result.iou_by_phase.values() if v is not None])
    result.boundary_error_s = _mean(errors)
    result.presence_by_phase = {p: _mean(v) for p, v in present.items()}
    result.frame_agreement = (
        sum(x == y for x, y in zip(grid_a, grid_b, strict=True)) / len(grid_a) if grid_a else None
    )
    result.kappa = cohens_kappa(grid_a, grid_b)
    result.primary_view = same_view / len(shared) if shared else None
    result.event_type = same_type / len(shared) if shared else None
    result.clip_miou = dict(sorted(per_clip.items(), key=lambda kv: (kv[1], kv[0])))
    return result


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(agreement: Agreement, *, expected_clips: int | None = None) -> str:
    lines = [f"Clips both annotated: {agreement.clips}"]
    if expected_clips is not None and agreement.clips < expected_clips:
        lines.append(
            f"WARNING: the overlap set should have {expected_clips} clips; only "
            f"{agreement.clips} were labelled by both. Agreement on so few is not reliable."
        )
    lines += ["", "| Phase | IoU | Agree it happens |", "|---|---:|---:|"]
    for phase in PHASES:
        lines.append(
            f"| {phase} | {_pct(agreement.iou_by_phase.get(phase))} | "
            f"{_pct(agreement.presence_by_phase.get(phase))} |"
        )
    boundary = (
        "n/a" if agreement.boundary_error_s is None else f"{agreement.boundary_error_s:.2f} s"
    )
    kappa = "n/a" if agreement.kappa is None else f"{agreement.kappa:.2f}"
    lines += [
        "",
        f"- mIoU: {_pct(agreement.miou)}",
        f"- Mean boundary difference (phases both marked): {boundary}",
        f"- Frame-wise agreement: {_pct(agreement.frame_agreement)} (Cohen's kappa {kappa})",
        f"- Same primary view: {_pct(agreement.primary_view)}; "
        f"same event type: {_pct(agreement.event_type)}",
    ]
    if agreement.clip_miou:
        worst = list(agreement.clip_miou.items())[:5]
        lines += ["", "Least agreed clips (look at these first):"]
        lines += [f"- {clip_id}: {_pct(value)}" for clip_id, value in worst]
    return "\n".join(lines) + "\n"
