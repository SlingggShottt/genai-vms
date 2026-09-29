"""Camera repository — SQLAlchemy queries against `core.cameras`. No
business rules here (uniqueness, permission checks); that's the router's job.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import Camera


async def get_camera_by_id(session: AsyncSession, camera_id: uuid.UUID) -> Camera | None:
    return await session.get(Camera, camera_id)


async def get_camera_by_code(session: AsyncSession, code: str) -> Camera | None:
    result = await session.execute(select(Camera).where(Camera.code == code))
    return result.scalar_one_or_none()


async def list_cameras(
    session: AsyncSession, *, limit: int, cursor: uuid.UUID | None
) -> list[Camera]:
    """Cursor pagination on `id`, newest first: uuid7 is time-ordered, so
    `ORDER BY id DESC` with `id < cursor` for the next page surfaces
    recently created rows by default — an ascending, no-cursor first page
    would show the same oldest N forever once the table passes `limit` rows.
    """
    stmt = select(Camera).order_by(Camera.id.desc()).limit(limit)
    if cursor is not None:
        stmt = stmt.where(Camera.id < cursor)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_all_cameras(session: AsyncSession) -> list[Camera]:
    """Every camera, enabled or not — for `/internal/v1/cameras` (the
    caller filters by `enabled`) and `/cameras/status` (an offline-but-
    enabled camera is still reportable status; a disabled one arguably
    shouldn't be queried at all, but that's the caller's call, not this
    repository's).
    """
    result = await session.execute(select(Camera).order_by(Camera.id))
    return list(result.scalars().all())


async def create_camera(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    rtsp_url: str,
    site_id: str,
    location_label: str | None,
    lat: float | None,
    lon: float | None,
    enabled: bool,
) -> Camera:
    camera = Camera(
        code=code,
        name=name,
        rtsp_url=rtsp_url,
        site_id=site_id,
        location_label=location_label,
        lat=lat,
        lon=lon,
        enabled=enabled,
    )
    session.add(camera)
    await session.flush()  # populates server-generated defaults (id, created_at) for the caller
    return camera


# Columns update_camera is allowed to touch. `code` isn't here: FR-CAM-01
# only lists name/RTSP URL/site/location label/lat-long as editable, and
# code is what everything else (segments, twins, Redis heartbeats) keys on.
UPDATABLE_FIELDS = frozenset(
    {"name", "rtsp_url", "site_id", "location_label", "lat", "lon", "enabled"}
)


async def update_camera(
    session: AsyncSession, camera: Camera, changes: dict[str, object]
) -> Camera:
    """Apply exactly the fields present in `changes` (e.g.
    `CameraUpdateRequest.model_dump(exclude_unset=True)`), `None` values
    included — unlike a per-field `is not None` check, this lets a caller
    actually clear a nullable column (`location_label`, `lat`, `lon`).
    The router is responsible for rejecting an explicit `null` for a
    non-nullable field before it gets here (see `_NON_NULLABLE_FIELDS` in
    api.api.cameras) — this function trusts `changes` as already valid.
    """
    for field, value in changes.items():
        if field in UPDATABLE_FIELDS:
            setattr(camera, field, value)
    # No flush: nothing reads back a server-generated value here — the
    # request-scoped session's commit (api.api.deps.get_session) persists it.
    return camera


async def delete_camera(session: AsyncSession, camera: Camera) -> None:
    await session.delete(camera)
