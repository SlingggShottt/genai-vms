"""`GET /tracks/{track_id}` — overlay side-panel data (P2-J6, FR-PLAY-03).
All roles can read, same as `/twin/{camera_id}/frames`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import User

from api.adapters.tracks import get_track_with_dwell
from api.api.deps import get_session
from api.api.errors import APIError
from api.api.security import get_current_user
from api.schemas import TrackSummaryOut

router = APIRouter(prefix="/tracks", tags=["tracks"])


@router.get("/{track_id}", response_model=TrackSummaryOut)
async def get_track_endpoint(
    track_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> TrackSummaryOut:
    found = await get_track_with_dwell(session, track_id)
    if found is None:
        raise APIError("NOT_FOUND", "Track not found.", status_code=status.HTTP_404_NOT_FOUND)
    track, dwell_s = found
    return TrackSummaryOut.from_model(track, dwell_s=dwell_s)
