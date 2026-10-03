"""The frames a candidate is judged on, kept while the candidate is built (P3-D4) — pure.

The VLM gate looks at a handful of keyframes with the flagged objects boxed. Deriving those later
from the twins would mean knowing where perception stored each segment's twin, which is
perception's business, so the engine notes the evidence as it goes: for every hit frame, the
keyframe and the boxes of the tracks the hit is about. An episode keeps a bounded, thinned sample
of them (`MAX_KEPT`) that always includes its first and its latest frame, and the sample travels
with the candidate in `events.candidates.details["evidence"]`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from vms_common.contracts.twin import Frame

T = TypeVar("T")

MAX_KEPT = 16  # frames kept per episode before the sample is thinned to half
MAX_BOXES = 8  # boxes kept per frame (a crowd is drawn by its most confident members)


class EvidenceBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str
    category: str
    bbox: tuple[float, float, float, float] = Field(description="normalized (x1, y1, x2, y2)")


class EvidenceFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: AwareDatetime
    segment_id: str
    keyframe_uri: str
    boxes: list[EvidenceBox] = Field(default_factory=list)


def frame_evidence(frame: Frame, segment_id: str, track_ids: Sequence[str]) -> EvidenceFrame:
    """The evidence one hit frame gives: its keyframe and the boxes of `track_ids` in it."""
    wanted = set(track_ids)
    flagged = sorted(
        (obj for obj in frame.objects if obj.track_id in wanted), key=lambda obj: -obj.conf
    )
    return EvidenceFrame(
        ts=frame.ts,
        segment_id=segment_id,
        keyframe_uri=frame.keyframe_uri,
        boxes=[
            EvidenceBox(track_id=obj.track_id, category=obj.category, bbox=obj.bbox)
            for obj in flagged[:MAX_BOXES]
        ],
    )


def spread(items: Sequence[T], k: int) -> list[T]:
    """`k` of `items`, evenly spaced and always including the first and the last (the last
    alone for `k == 1`). All of them when there are no more than `k`."""
    n = len(items)
    if k <= 0:
        return []
    if n <= k:
        return list(items)
    if k == 1:
        return [items[-1]]
    return [items[round(i * (n - 1) / (k - 1))] for i in range(k)]


def add_evidence(
    kept: Sequence[EvidenceFrame], new: EvidenceFrame, *, limit: int = MAX_KEPT
) -> list[EvidenceFrame]:
    """`kept` plus `new`, thinned to half of `limit` (first and latest kept) once it would
    exceed `limit`. A frame already kept (same keyframe) is not added twice."""
    if any(frame.keyframe_uri == new.keyframe_uri for frame in kept):
        return list(kept)
    grown = [*kept, new]
    return spread(grown, limit // 2) if len(grown) > limit else grown
