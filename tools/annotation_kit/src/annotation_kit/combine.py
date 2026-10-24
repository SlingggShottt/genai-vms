"""One set of phase labels from several sources, each clip labelled by the best source it has, and
every label saying where it came from.

For each clip the order is: what a person submitted, else a model's draft, else the dataset's own
crime span. The source is written into the label's `annotator`, because a result computed from the
labels is only as good as the labels, and a reader has to be able to split it:

    human:from-scratch            a person marked it with no draft behind it
    human:accepted-draft:<v>      a person submitted a draft exactly as drafted
    human:corrected-draft:<v>     a person changed a draft, then submitted
    draft:<v>:<how>               nobody opened it: the model's draft as it is (`how` says whether
                                  the model looked at frames or only applied a rule)
    dataset-span:ucf-crime        the dataset's crime span, three stages at most

`group()` collapses these to the four a report should show. Only the first group is a person's
judgement; a person who accepts a draft without watching has still put their name to it, which is
why `human:accepted-draft` is its own source and is never merged with `from-scratch`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from annotation_kit import draftedits, phaseconvert
from annotation_kit.candidates import PhaseCandidate, clip_uri
from annotation_kit.schema import ClipView, PhaseLabelClip, PhaseSpan

HUMAN_SCRATCH = "human:from-scratch"
SPAN = "dataset-span:ucf-crime"
MIN_STAGE_S = 0.1

GROUPS = ("human", "model draft (looked at the clip)", "model draft (rule only)", "dataset span")


def group(source: str | None) -> str:
    """The report group of a label source."""
    if source is None:
        return "unknown"
    if source.startswith("human:"):
        return GROUPS[0]
    if source.startswith("draft:"):
        return GROUPS[2] if source.endswith(":padding-rule") else GROUPS[1]
    if source == SPAN:
        return GROUPS[3]
    return "unknown"


def _slug(text: str) -> str:
    return "-".join(text.split())


@dataclass
class Combined:
    clips: list[PhaseLabelClip] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # a fallback or a clip left out, and why
    missing: list[str] = field(default_factory=list)  # candidates with no label from any source

    def sources(self) -> dict[str, str]:
        return {c.clip_id: c.annotator or "" for c in self.clips}

    def counts(self) -> dict[str, int]:
        return dict(Counter(group(c.annotator) for c in self.clips))

    def by_source(self) -> dict[str, int]:
        return dict(sorted(Counter(c.annotator for c in self.clips).items()))


def draft_clip(
    candidate: PhaseCandidate,
    draft: Mapping[str, Any],
    *,
    version: str,
    clip_prefix: str,
) -> PhaseLabelClip | None:
    """A candidate's draft as a label, its stages cut to the clip. None if nothing is left."""
    duration = candidate.duration_s
    spans: list[PhaseSpan] = []
    for phase, start, end in draft["stages"]:
        start, end = float(start), min(float(end), duration)
        if end - start >= MIN_STAGE_S and start < duration:
            spans.append(PhaseSpan(phase=phase, start_s=start, end_s=end))
    if not spans:
        return None
    how = _slug(str(draft.get("how", "frames")))
    return PhaseLabelClip(
        clip_id=candidate.candidate_id,
        source_video=candidate.source_video,
        event_type=candidate.event_type,
        primary_view=candidate.primary_view,
        views=[
            ClipView(camera=v.camera, video_uri=clip_uri(clip_prefix, candidate, v))
            for v in candidate.views
        ],
        phases=spans,
        annotator=f"draft:{version}:{how}",
    )


def combine(
    candidates: Sequence[PhaseCandidate],
    *,
    hand_export: Sequence[Mapping[str, Any]] = (),
    drafts: Sequence[Mapping[str, Any]] = (),
    span_labels: Sequence[PhaseLabelClip] = (),
    clip_prefix: str = "local://clips",
) -> Combined:
    """`drafts` are drafts files in order: for a clip in more than one, the later one wins."""
    converted = phaseconvert.convert_phases(hand_export)
    hand = {c.clip_id: c for c in converted.clips}
    edits = {e.clip_id: e for e in draftedits.clip_edits(hand_export)}
    draft_of: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for doc in drafts:
        for item in doc["clips"]:
            draft_of[str(item["candidate_id"])] = (str(doc["model_version"]), item)
    spans = {c.clip_id: c for c in span_labels}

    out = Combined()
    for candidate in candidates:
        cid = candidate.candidate_id
        tried_hand = cid in edits and cid not in hand
        if cid in hand:
            edit = edits.get(cid)
            if edit is None or edit.origin == draftedits.SCRATCH:
                source = HUMAN_SCRATCH
            else:
                kind = "accepted" if edit.identical else "corrected"
                source = f"human:{kind}-draft:{edit.origin}"
            out.clips.append(hand[cid].model_copy(update={"annotator": source}))
            continue
        if tried_hand:
            out.notes.append(f"{cid}: the person's marks were rejected by the converter")
        if cid in draft_of:
            version, item = draft_of[cid]
            label = draft_clip(candidate, item, version=version, clip_prefix=clip_prefix)
            if label is not None:
                out.clips.append(label)
                continue
            out.notes.append(f"{cid}: the draft has no usable stage")
        if cid in spans:
            out.clips.append(spans[cid].model_copy(update={"annotator": SPAN}))
            continue
        out.missing.append(cid)
    return out


def summary_table(combined: Combined) -> str:
    counts = combined.counts()
    lines = ["| source | clips |", "|---|---:|"]
    lines += [f"| {g} | {counts[g]} |" for g in GROUPS if g in counts]
    lines += ["", "| exact source | clips |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in combined.by_source().items()]
    return "\n".join(lines)
