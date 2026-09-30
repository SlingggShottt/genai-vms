"""Recordings repository — SQLAlchemy queries against `media.segments` and
`vision.minute_counts` (P2-J3). No business rules here; see
`api.domain.recordings` for gap/playlist/density logic.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import MinuteCount, Segment


async def list_segments_in_range(
    session: AsyncSession, *, camera_id: str, start: datetime, end: datetime
) -> list[Segment]:
    """Segments overlapping `[start, end)` — a segment need not start
    inside the window, just intersect it, so playback near a boundary
    doesn't lose the segment covering that boundary.
    """
    stmt = (
        select(Segment)
        .where(
            Segment.camera_id == camera_id,
            Segment.start_ts < end,
            Segment.end_ts > start,
        )
        .order_by(Segment.start_ts)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def sum_minute_counts_in_range(
    session: AsyncSession, *, camera_id: str, start: datetime, end: datetime
) -> list[tuple[datetime, int]]:
    """Per-minute total across every category (`vision.minute_counts` is
    keyed by camera/category/minute — density sums categories away, see
    `api.domain.recordings.bucket_density`'s docstring for why that's a
    deliberate simplification, not an oversight).
    """
    stmt = (
        select(MinuteCount.minute_ts, func.sum(MinuteCount.count))
        .where(
            MinuteCount.camera_id == camera_id,
            MinuteCount.minute_ts >= start,
            MinuteCount.minute_ts < end,
        )
        .group_by(MinuteCount.minute_ts)
        .order_by(MinuteCount.minute_ts)
    )
    result = await session.execute(stmt)
    return [(minute_ts, int(total)) for minute_ts, total in result.all()]
