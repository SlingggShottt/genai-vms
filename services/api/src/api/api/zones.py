"""Zone management endpoints (FR-CAM-03). Read: any authenticated role.
Write (create/update/delete): admin only. Routes mix two prefixes per
design_architecture.md §9 (`/cameras/{camera_id}/zones` to list/create,
flat `/zones/{zone_id}` to update/delete), so this router carries no
single `prefix=` — each route spells out its own full path.

`camera_id` here is `core.cameras.id`, the UUID — matching every other
resource id this API exposes (`/cameras/{id}`, `/users/{id}`, ...). That's
the opposite of `GET /internal/v1/zones` (`api/internal.py`), which reports
the camera's **code** instead, matching what perception/events already
know from Kafka messages. See `libs/vms_common/types.py` and
design_architecture.md §5.1 for the full split.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import User, UserRole

from api.adapters.cameras import get_camera_by_id
from api.adapters.zones import (
    create_zone,
    delete_zone,
    get_zone_by_id,
    list_zones_for_camera,
    update_zone,
)
from api.api.deps import get_session
from api.api.errors import APIError
from api.api.security import get_current_user, require_role
from api.schemas import ZoneCreateRequest, ZoneOut, ZonesPage, ZoneUpdateRequest

router = APIRouter(tags=["zones"])

_admin_only = require_role(UserRole.ADMIN)

# name/zone_type/polygon are NOT NULL columns — an explicit `null` for one
# of these in a PATCH body is a client error (400), not a silent no-op or
# a DB constraint violation. `schedule` is nullable, so null there is a
# legitimate "clear it" (see api.schemas.ZoneUpdateRequest's docstring).
_NON_NULLABLE_FIELDS = frozenset({"name", "zone_type", "polygon"})


def _parse_uuid(value: str, *, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", f"Malformed {what} id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc


@router.get("/cameras/{camera_id}/zones", response_model=ZonesPage)
async def list_zones_endpoint(
    camera_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> ZonesPage:
    camera = await get_camera_by_id(session, _parse_uuid(camera_id, what="camera"))
    if camera is None:
        raise APIError("NOT_FOUND", "Camera not found.", status_code=status.HTTP_404_NOT_FOUND)
    zones = await list_zones_for_camera(session, camera.id)
    return ZonesPage(items=[ZoneOut.from_model(z) for z in zones])


@router.post(
    "/cameras/{camera_id}/zones", response_model=ZoneOut, status_code=status.HTTP_201_CREATED
)
async def create_zone_endpoint(
    camera_id: str,
    body: ZoneCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(_admin_only)],
) -> ZoneOut:
    camera = await get_camera_by_id(session, _parse_uuid(camera_id, what="camera"))
    if camera is None:
        raise APIError("NOT_FOUND", "Camera not found.", status_code=status.HTTP_404_NOT_FOUND)
    zone = await create_zone(
        session,
        camera_id=camera.id,
        name=body.name,
        zone_type=body.zone_type,
        polygon=body.polygon,
        schedule=body.schedule.model_dump() if body.schedule else None,
    )
    return ZoneOut.from_model(zone)


@router.patch("/zones/{zone_id}", response_model=ZoneOut)
async def update_zone_endpoint(
    zone_id: str,
    body: ZoneUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(_admin_only)],
) -> ZoneOut:
    target = await get_zone_by_id(session, _parse_uuid(zone_id, what="zone"))
    if target is None:
        raise APIError("NOT_FOUND", "Zone not found.", status_code=status.HTTP_404_NOT_FOUND)

    changes = body.model_dump(exclude_unset=True)
    nulled_required = [f for f in _NON_NULLABLE_FIELDS if changes.get(f, "unset") is None]
    if nulled_required:
        raise APIError(
            "VALIDATION_ERROR",
            f"{', '.join(sorted(nulled_required))} cannot be null.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if "schedule" in changes and changes["schedule"] is not None:
        changes["schedule"] = body.schedule.model_dump() if body.schedule else None

    target = await update_zone(session, target, changes)
    return ZoneOut.from_model(target)


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone_endpoint(
    zone_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(_admin_only)],
) -> None:
    target = await get_zone_by_id(session, _parse_uuid(zone_id, what="zone"))
    if target is None:
        raise APIError("NOT_FOUND", "Zone not found.", status_code=status.HTTP_404_NOT_FOUND)
    await delete_zone(session, target)
