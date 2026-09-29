"""Internal, service-to-service endpoints (design_architecture.md §15) —
guarded by `require_service_token`, never a user JWT/role.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from vms_common.contracts.camera import CameraInternal, CamerasInternalResponse

from api.adapters.cameras import list_all_cameras
from api.api.deps import get_session
from api.api.security import require_service_token

router = APIRouter(
    prefix="/internal/v1", tags=["internal"], dependencies=[Depends(require_service_token)]
)


@router.get("/cameras", response_model=CamerasInternalResponse)
async def internal_cameras_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CamerasInternalResponse:
    """All cameras, enabled or not (design_architecture.md §16: ingestion's
    `resolve_cameras` filters by `enabled` on its own side) — matches
    `libs/vms_common/fixtures/cameras_internal.json`.
    """
    cameras = await list_all_cameras(session)
    return CamerasInternalResponse(
        cameras=[
            CameraInternal(
                id=str(c.id),
                code=c.code,
                name=c.name,
                rtsp_url=c.rtsp_url,
                site_id=c.site_id,
                location_label=c.location_label,
                lat=c.lat,
                lon=c.lon,
                enabled=c.enabled,
            )
            for c in cameras
        ]
    )
