"""Camera management endpoints (FR-CAM-01, FR-CAM-02). Read: any
authenticated role. Write (create/update/delete): admin only.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from vms_db.models import User, UserRole

from api.adapters.camera_status import get_camera_statuses
from api.adapters.cameras import (
    create_camera,
    delete_camera,
    get_camera_by_code,
    get_camera_by_id,
    list_all_cameras,
    list_cameras,
    update_camera,
)
from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import get_current_user, require_role
from api.schemas import (
    CameraCreateRequest,
    CameraOut,
    CamerasPage,
    CamerasStatusResponse,
    CameraStatusOut,
    CameraUpdateRequest,
)

router = APIRouter(prefix="/cameras", tags=["cameras"])

_admin_only = require_role(UserRole.ADMIN)

# name/rtsp_url/site_id/enabled are NOT NULL columns — an explicit `null`
# for one of these in a PATCH body is a client error (400), not a silent
# no-op or a DB constraint violation. location_label/lat/lon are nullable,
# so null there is a legitimate "clear this field".
_NON_NULLABLE_FIELDS = frozenset({"name", "rtsp_url", "site_id", "enabled"})


def _parse_camera_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", "Malformed camera id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc


@router.get("", response_model=CamerasPage)
async def list_cameras_endpoint(
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> CamerasPage:
    cursor_id = _parse_camera_id(cursor) if cursor else None
    rows = await list_cameras(session, limit=limit + 1, cursor=cursor_id)
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = str(page[-1].id) if has_more and page else None
    return CamerasPage(items=[CameraOut.from_model(c) for c in page], next_cursor=next_cursor)


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
async def create_camera_endpoint(
    body: CameraCreateRequest,
    session: SessionDep,
    _admin: Annotated[User, Depends(_admin_only)],
) -> CameraOut:
    if await get_camera_by_code(session, body.code) is not None:
        raise APIError(
            "CONFLICT",
            "A camera with this code already exists.",
            status_code=status.HTTP_409_CONFLICT,
        )
    try:
        camera = await create_camera(
            session,
            code=body.code,
            name=body.name,
            rtsp_url=body.rtsp_url,
            site_id=body.site_id,
            location_label=body.location_label,
            lat=body.lat,
            lon=body.lon,
            enabled=body.enabled,
        )
    except IntegrityError as exc:
        # The precheck above doesn't rule out a concurrent request creating
        # the same code between the check and this insert; the DB's own
        # unique constraint is the real guard.
        raise APIError(
            "CONFLICT",
            "A camera with this code already exists.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    return CameraOut.from_model(camera)


@router.get("/status", response_model=CamerasStatusResponse)
async def camera_status_endpoint(
    request: Request,
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_user)],
) -> CamerasStatusResponse:
    cameras = await list_all_cameras(session)
    statuses = await get_camera_statuses(request.app.state.redis_client, [c.code for c in cameras])
    return CamerasStatusResponse(
        cameras=[
            CameraStatusOut(id=str(c.id), code=c.code, name=c.name, status=statuses[c.code])
            for c in cameras
        ]
    )


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera_endpoint(
    camera_id: str,
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_user)],
) -> CameraOut:
    camera = await get_camera_by_id(session, _parse_camera_id(camera_id))
    if camera is None:
        raise APIError("NOT_FOUND", "Camera not found.", status_code=status.HTTP_404_NOT_FOUND)
    return CameraOut.from_model(camera)


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_camera_endpoint(
    camera_id: str,
    body: CameraUpdateRequest,
    session: SessionDep,
    _admin: Annotated[User, Depends(_admin_only)],
) -> CameraOut:
    target = await get_camera_by_id(session, _parse_camera_id(camera_id))
    if target is None:
        raise APIError("NOT_FOUND", "Camera not found.", status_code=status.HTTP_404_NOT_FOUND)

    changes = body.model_dump(exclude_unset=True)
    nulled_required = [f for f in _NON_NULLABLE_FIELDS if changes.get(f, "unset") is None]
    if nulled_required:
        raise APIError(
            "VALIDATION_ERROR",
            f"{', '.join(sorted(nulled_required))} cannot be null.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    target = await update_camera(session, target, changes)
    return CameraOut.from_model(target)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera_endpoint(
    camera_id: str,
    session: SessionDep,
    _admin: Annotated[User, Depends(_admin_only)],
) -> None:
    target = await get_camera_by_id(session, _parse_camera_id(camera_id))
    if target is None:
        raise APIError("NOT_FOUND", "Camera not found.", status_code=status.HTTP_404_NOT_FOUND)
    await delete_camera(session, target)
