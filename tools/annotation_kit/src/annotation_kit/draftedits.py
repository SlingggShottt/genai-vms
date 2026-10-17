"""How much a person changed a model's draft, from a Label Studio export.

When a model drafts the stages and a person corrects them, the corrected labels are the person's
only to the extent the person really looked. Two numbers say how far to trust them: how many clips
were submitted exactly as drafted, and how far the rest moved. Nearly all unchanged is as suspicious
as nearly all rewritten: the first can mean the drafts were very good or that nobody checked, the
second that the drafts were no use. Say which in the report, with these figures.

Label Studio keeps the link: an annotation made from a prediction carries it
(`annotation["prediction"]`, with the draft's `result`, `model_version` and `score`), so the export
alone is enough. A clip whose annotation has no such link was marked from scratch, and the labels of
those are the cleaner ones: keep the two kinds apart when scoring a model.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from annotation_kit.phaseconfig import FRAMERATE, PHASE

SCRATCH = "scratch"


@dataclass
class ClipEdit:
    clip_id: str
    origin: str  # "scratch" or the draft's model_version
    score: float | None = None
    identical: bool = False
    iou: float | None = None  # over the stages either of them marks; None for a clip from scratch
    moved: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    mean_shift_s: float | None = None  # of the boundaries of stages in both
    answers_changed: list[str] = field(default_factory=list)


def stages(result: Sequence[Mapping[str, Any]]) -> dict[str, tuple[int, int]]:
    """{phase: (first frame, last frame)} from the timeline marks of one result."""
    out: dict[str, tuple[int, int]] = {}
    for item in result or []:
        value = item.get("value") or {}
        if item.get("type") == "timelinelabels" and item.get("from_name") == PHASE:
            for label in value.get("timelinelabels") or []:
                for span in value.get("ranges") or []:
                    out[str(label)] = (int(span["start"]), int(span["end"]))
    return out


def answers(result: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in result or []:
        value = item.get("value") or {}
        if item.get("type") == "choices" and value.get("choices"):
            out[str(item.get("from_name"))] = str(value["choices"][0])
    return out


def _iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]) + 1)
    union = (a[1] - a[0] + 1) + (b[1] - b[0] + 1) - inter
    return inter / union if union else 0.0


def compare(
    draft: Sequence[Mapping[str, Any]], final: Sequence[Mapping[str, Any]], *, fps: int
) -> dict:
    d, f = stages(draft), stages(final)
    both = sorted(set(d) & set(f))
    moved = [p for p in both if d[p] != f[p]]
    union = sorted(set(d) | set(f))
    ious = [_iou(d[p], f[p]) if p in d and p in f else 0.0 for p in union]
    shifts = [(abs(d[p][0] - f[p][0]) + abs(d[p][1] - f[p][1])) / 2 / fps for p in moved]
    ad, af = answers(draft), answers(final)
    return {
        "identical": d == f and ad == af,
        "iou": statistics.fmean(ious) if ious else None,
        "moved": moved,
        "added": sorted(set(f) - set(d)),
        "removed": sorted(set(d) - set(f)),
        "mean_shift_s": statistics.fmean(shifts) if shifts else None,
        "answers_changed": sorted(k for k in set(ad) | set(af) if ad.get(k) != af.get(k)),
    }


def clip_edits(
    export: Sequence[Mapping[str, Any]], *, model_version: str | None = None
) -> list[ClipEdit]:
    """One entry per task with a finished annotation, using the person's latest one. With
    `model_version`, a draft from another model counts as from scratch."""
    out: list[ClipEdit] = []
    for item in export:
        data = item.get("data") or {}
        finished = [
            a
            for a in item.get("annotations") or []
            if a.get("result") and not a.get("was_cancelled")
        ]
        if not finished:
            continue
        latest = max(
            finished, key=lambda a: (str(a.get("updated_at") or ""), int(a.get("id") or 0))
        )
        draft = latest.get("prediction") or {}
        version = draft.get("model_version")
        clip_id = str(data.get("candidate_id", item.get("id")))
        if not draft.get("result") or (model_version and version != model_version):
            out.append(ClipEdit(clip_id, SCRATCH))
            continue
        fps = int(data.get("timeline_fps") or FRAMERATE)
        out.append(
            ClipEdit(
                clip_id,
                str(version),
                draft.get("score"),
                **compare(draft["result"], latest["result"], fps=fps),
            )
        )
    return out


def summarise(edits: Sequence[ClipEdit]) -> dict[str, Any]:
    drafted = [e for e in edits if e.origin != SCRATCH]
    scratch = [e for e in edits if e.origin == SCRATCH]
    ious = [e.iou for e in drafted if e.iou is not None]
    shifts = [e.mean_shift_s for e in drafted if e.mean_shift_s is not None]
    return {
        "clips": len(edits),
        "from_scratch": len(scratch),
        "from_a_draft": len(drafted),
        "submitted_exactly_as_drafted": sum(e.identical for e in drafted),
        "share_unchanged": round(sum(e.identical for e in drafted) / len(drafted), 3)
        if drafted
        else None,
        "mean_iou_with_the_draft": round(statistics.fmean(ious), 3) if ious else None,
        "mean_boundary_shift_s": round(statistics.fmean(shifts), 2) if shifts else None,
        "stage_changes": {
            "moved": sum(len(e.moved) for e in drafted),
            "added": sum(len(e.added) for e in drafted),
            "removed": sum(len(e.removed) for e in drafted),
        },
        "answers_changed": sum(bool(e.answers_changed) for e in drafted),
        "scratch_clips": sorted(e.clip_id for e in scratch),
        "drafted_clips": sorted(e.clip_id for e in drafted),
    }


def markdown(edits: Sequence[ClipEdit], summary: Mapping[str, Any]) -> str:
    lines = ["| clip | origin | as drafted | IoU with draft | changes |", "|---|---|---|---|---|"]
    for e in sorted(edits, key=lambda e: e.clip_id):
        if e.origin == SCRATCH:
            lines.append(f"| {e.clip_id} | from scratch | | | |")
            continue
        changes = "; ".join(
            part
            for part in (
                f"moved {', '.join(e.moved)}" if e.moved else "",
                f"added {', '.join(e.added)}" if e.added else "",
                f"removed {', '.join(e.removed)}" if e.removed else "",
                f"changed {', '.join(e.answers_changed)}" if e.answers_changed else "",
            )
            if part
        )
        lines.append(
            f"| {e.clip_id} | draft | {'yes' if e.identical else 'no'} | "
            f"{'' if e.iou is None else f'{e.iou:.2f}'} | {changes} |"
        )
    n = summary["from_a_draft"]
    lines += [
        "",
        f"{summary['clips']} clips: {summary['from_scratch']} marked from scratch, "
        f"{n} corrected from a draft.",
    ]
    if n:
        text = (
            f"Of the {n} drafted, {summary['submitted_exactly_as_drafted']} were submitted "
            f"exactly as drafted ({summary['share_unchanged']:.0%}); mean overlap with the "
            f"draft {summary['mean_iou_with_the_draft']:.2f}"
        )
        if summary["mean_boundary_shift_s"] is not None:
            text += f"; mean boundary shift {summary['mean_boundary_shift_s']} s"
        lines.append(text + ".")
        share = summary["share_unchanged"]
        if share is not None and share >= 0.9 and n >= 5:
            lines.append(
                "**Nearly everything was accepted unchanged: say how it was checked, or re-mark a "
                "sample from scratch.**"
            )
        if share == 0 and n >= 5:
            lines.append(
                "Nothing was accepted as drafted: the drafts may be no use, or too few were "
                "checked."
            )
    return "\n".join(lines) + "\n"
