"""Per-(camera, category, minute) density from one segment's twin — no I/O.

`vision.minute_counts` backs the density sparkline (P2-J5) and the
assistant's `count_objects` tool (design_architecture.md §10.3). A segment
is ~10s, so it usually falls inside one minute bucket; `compute_minute_counts`
splits across a boundary when it doesn't. Perception already drops frames
with zero detections from `twin.frames` (see perception's worker.py), so a
minute with no matches in this segment contributes no row at all here —
absence, not an explicit zero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import NamedTuple

from vms_common.contracts.twin import TwinV1


class MinuteCountKey(NamedTuple):
    minute_ts: datetime
    category: str


def minute_bucket(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def compute_minute_counts(twin: TwinV1) -> dict[MinuteCountKey, int]:
    """Max simultaneous per-category object count, per minute, across
    `twin.frames`. Two segments overlapping the same minute each contribute
    their own local max; callers merge across segments with `GREATEST`
    (see `indexer.adapters.repository`), so this is intentionally a
    per-segment view, not a whole-minute one.
    """
    counts: dict[MinuteCountKey, int] = defaultdict(int)
    for frame in twin.frames:
        minute = minute_bucket(frame.ts)
        per_category: dict[str, int] = defaultdict(int)
        for obj in frame.objects:
            per_category[obj.category] += 1
        for category, n in per_category.items():
            key = MinuteCountKey(minute, category)
            if n > counts[key]:
                counts[key] = n
    return dict(counts)
