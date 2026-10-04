"""Recordings endpoints: segment index, HLS VOD playlist, detection
density (P2-J3, FR-PLAY-01, FR-PLAY-02). All roles can read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession
from vms_common.storage.s3 import S3Client
from vms_db.models import User

from api.adapters.cameras import get_camera_by_code
from api.adapters.recordings import list_segments_in_range, sum_minute_counts_in_range
from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import get_current_user
from api.domain.recordings import (
    MinuteCountRow,
    SegmentWindow,
    bucket_density,
    build_playlist_m3u8,
    build_timeline,
)
from api.schemas import (
    DensityBucketOut,
    GapItemOut,
    RecordingsDensityResponse,
    RecordingsSegmentsResponse,
    SegmentItemOut,
)

router = APIRouter(prefix="/recordings", tags=["recordings"])

DEFAULT_DENSITY_BUCKET_SECONDS = 60


async def _require_camera(session: AsyncSession, camera_id: str) -> None:
    if await get_camera_by_code(session, camera_id) is None:
        raise APIError("NOT_FOUND", "Camera not found.", status_code=status.HTTP_404_NOT_FOUND)


def _require_valid_range(start: AwareDatetime, end: AwareDatetime) -> None:
    if end <= start:
        raise APIError(
            "VALIDATION_ERROR", "end must be after start.", status_code=status.HTTP_400_BAD_REQUEST
        )


async def _presigned_segment_windows(
    s3: S3Client, session: AsyncSession, *, camera_id: str, start: AwareDatetime, end: AwareDatetime
) -> list[SegmentWindow]:
    segments = await list_segments_in_range(session, camera_id=camera_id, start=start, end=end)
    return [
        SegmentWindow(
            segment_id=seg.segment_id,
            start_ts=seg.start_ts,
            end_ts=seg.end_ts,
            uri=await s3.presign_get(seg.uri),
        )
        for seg in segments
    ]


@router.get("/{camera_id}/segments", response_model=RecordingsSegmentsResponse)
async def list_segments_endpoint(
    camera_id: str,
    request: Request,
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_user)],
) -> RecordingsSegmentsResponse:
    _require_valid_range(start, end)
    await _require_camera(session, camera_id)

    windows = await _presigned_segment_windows(
        request.app.state.s3, session, camera_id=camera_id, start=start, end=end
    )
    timeline = build_timeline(windows, range_start=start, range_end=end)
    items = [
        SegmentItemOut.from_domain(item)
        if isinstance(item, SegmentWindow)
        else GapItemOut.from_domain(item)
        for item in timeline
    ]
    return RecordingsSegmentsResponse(camera_id=camera_id, start=start, end=end, items=items)


@router.get("/{camera_id}/playlist.m3u8")
async def playlist_endpoint(
    camera_id: str,
    request: Request,
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    _require_valid_range(start, end)
    await _require_camera(session, camera_id)

    windows = await _presigned_segment_windows(
        request.app.state.s3, session, camera_id=camera_id, start=start, end=end
    )
    timeline = build_timeline(windows, range_start=start, range_end=end)
    playlist = build_playlist_m3u8(timeline)
    return Response(content=playlist, media_type="application/vnd.apple.mpegurl")


@router.get("/{camera_id}/density", response_model=RecordingsDensityResponse)
async def density_endpoint(
    camera_id: str,
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_user)],
    bucket: Annotated[int, Query(gt=0)] = DEFAULT_DENSITY_BUCKET_SECONDS,
) -> RecordingsDensityResponse:
    _require_valid_range(start, end)
    await _require_camera(session, camera_id)

    rows = await sum_minute_counts_in_range(session, camera_id=camera_id, start=start, end=end)
    buckets = bucket_density(
        [MinuteCountRow(minute_ts, count) for minute_ts, count in rows],
        range_start=start,
        range_end=end,
        bucket_seconds=bucket,
    )
    return RecordingsDensityResponse(
        camera_id=camera_id,
        start=start,
        end=end,
        bucket_seconds=bucket,
        buckets=[DensityBucketOut.from_domain(b) for b in buckets],
    )
