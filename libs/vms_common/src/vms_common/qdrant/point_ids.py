"""Deterministic Qdrant point ids — no I/O.

Qdrant upserts are a natural "insert or overwrite" by point id, so an
indexer that always derives the *same* id for the *same* logical point
gets "re-runs overwrite, no duplicates" (P2-J2 AC) for free, with no extra
bookkeeping. Ids are UUID5s over a fixed namespace, so they're stable
across process restarts and code versions (as long as the key strings
below don't change — treat changing them as a breaking change, same as a
contract version bump).
"""

from __future__ import annotations

import uuid

# Fixed, arbitrary namespace for every point id this project derives —
# scopes them away from unrelated UUID5s (e.g. ids some other library in
# this codebase might derive from the same input strings for a different
# purpose).
_NAMESPACE = uuid.UUID("6f6e8b2a-9b1e-4d8c-8f1a-6a2f5f8b0c31")


def frame_point_id(segment_id: str, frame_idx: int) -> str:
    """One point per `twin.frames[i]`. `frame_idx` is `Frame.idx` — the
    sampled-frame ordinal perception assigns, which is also that frame's
    row in the segment's `.npz` `frame_vectors` (see `indexer.README.md`
    on why no separate lookup is needed).
    """
    return str(uuid.uuid5(_NAMESPACE, f"frame:{segment_id}:{frame_idx}"))


def track_point_id(track_id: str, segment_id: str) -> str:
    """One point per `twin.tracks[i]` — a track's best crop *for this
    segment* (a track spanning several segments gets one point per
    segment, matching `vision.track_segments`' own granularity).
    """
    return str(uuid.uuid5(_NAMESPACE, f"track:{track_id}:{segment_id}"))


def knowledge_point_id(doc_type: str, ref_id: str, part: str = "") -> str:
    """One point per indexed text: an event's caption, or one section of an incident report
    (`part` = "summary", "phase:action", …). Re-indexing the same text overwrites it."""
    return str(uuid.uuid5(_NAMESPACE, f"knowledge:{doc_type}:{ref_id}:{part}"))
