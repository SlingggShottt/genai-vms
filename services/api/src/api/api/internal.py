"""Internal, service-to-service endpoints (design_architecture.md §15) —
guarded by `require_service_token`, never a user JWT/role.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from vms_common.contracts.camera import CameraInternal, CamerasInternalResponse
from vms_common.contracts.zones import ZoneInternal, ZoneSchedule, ZonesInternalResponse

from api.adapters.cameras import list_all_cameras
from api.adapters.zones import list_all_zones
from api.api.deps import SessionDep
from api.api.security import require_service_token

router = APIRouter(
    prefix="/internal/v1", tags=["internal"], dependencies=[Depends(require_service_token)]
)


@router.get("/cameras", response_model=CamerasInternalResponse)
async def internal_cameras_endpoint(
    session: SessionDep,
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


@router.get("/zones", response_model=ZonesInternalResponse)
async def internal_zones_endpoint(
    session: SessionDep,
) -> ZonesInternalResponse:
    """Matches `libs/vms_common/fixtures/zones_internal.json` — note
    `camera_id` here is the camera's **code** (e.g. `cam03`), not its
    `core.cameras.id` UUID the public `/cameras/{id}/zones` router uses.
    Perception/events only ever see camera codes (from `segment.v1`), so
    that's what this internal contract exposes too.
    """
    cameras = await list_all_cameras(session)
    camera_codes = {c.id: c.code for c in cameras}
    zones = await list_all_zones(session)
    return ZonesInternalResponse(
        zones=[
            ZoneInternal(
                id=str(z.id),
                camera_id=camera_codes[z.camera_id],
                name=z.name,
                zone_type=z.zone_type,
                polygon=z.polygon,
                schedule=ZoneSchedule.model_validate(z.schedule) if z.schedule else None,
            )
            for z in zones
            if z.camera_id in camera_codes
        ]
    )
