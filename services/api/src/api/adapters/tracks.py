"""Track summary repository — `vision.tracks` + `vision.track_segments`
(P2-J6 overlay side panel).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import Track, TrackSegment


async def get_track_with_dwell(session: AsyncSession, track_id: str) -> tuple[Track, float] | None:
    track = await session.get(Track, track_id)
    if track is None:
        return None
    result = await session.execute(
        select(func.coalesce(func.sum(TrackSegment.dwell_s), 0.0)).where(
            TrackSegment.track_id == track_id
        )
    )
    return track, result.scalar_one()
