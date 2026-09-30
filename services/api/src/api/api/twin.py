"""`GET /twin/{camera_id}/frames` — overlay-ready bboxes for playback
(P2-J3, FR-PLAY-03 groundwork). All roles can read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import User

from api.adapters.cameras import get_camera_by_code
from api.adapters.recordings import list_segments_in_range
from api.adapters.twin_frames import frames_for_segments
from api.api.deps import get_session
from api.api.errors import APIError
from api.api.security import get_current_user
from api.schemas import OverlayFrameOut, OverlayObjectOut, TwinFramesResponse

router = APIRouter(prefix="/twin", tags=["twin"])

# "for a <= 60s window" (P2-J3 AC) — each matched segment's twin document
# is fetched whole from S3, so a wide-open range would mean fetching and
# parsing a lot of JSON per request; the frontend only ever needs a short
# window in view at once (overlay is synced to the current playhead).
MAX_WINDOW_SECONDS = 60


@router.get("/{camera_id}/frames", response_model=TwinFramesResponse)
async def twin_frames_endpoint(
    camera_id: str,
    request: Request,
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> TwinFramesResponse:
    if end <= start:
        raise APIError(
            "VALIDATION_ERROR", "end must be after start.", status_code=status.HTTP_400_BAD_REQUEST
        )
    if (end - start).total_seconds() > MAX_WINDOW_SECONDS:
        raise APIError(
            "VALIDATION_ERROR",
            f"window must be <= {MAX_WINDOW_SECONDS}s.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if await get_camera_by_code(session, camera_id) is None:
        raise APIError("NOT_FOUND", "Camera not found.", status_code=status.HTTP_404_NOT_FOUND)

    segments = await list_segments_in_range(session, camera_id=camera_id, start=start, end=end)
    frames = await frames_for_segments(request.app.state.s3, segments, start=start, end=end)

    return TwinFramesResponse(
        camera_id=camera_id,
        start=start,
        end=end,
        frames=[
            OverlayFrameOut(
                ts=frame.ts,
                objects=[
                    OverlayObjectOut(track_id=obj.track_id, category=obj.category, bbox=obj.bbox)
                    for obj in frame.objects
                ],
            )
            for frame in frames
        ],
    )
