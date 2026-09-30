"""Zone repository — SQLAlchemy queries against `core.zones`. No business
rules here (uniqueness, permission checks); that's the router's job.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import Zone, ZoneType


async def get_zone_by_id(session: AsyncSession, zone_id: uuid.UUID) -> Zone | None:
    return await session.get(Zone, zone_id)


async def list_zones_for_camera(session: AsyncSession, camera_id: uuid.UUID) -> list[Zone]:
    result = await session.execute(
        select(Zone).where(Zone.camera_id == camera_id).order_by(Zone.created_at)
    )
    return list(result.scalars().all())


async def list_all_zones(session: AsyncSession) -> list[Zone]:
    """Every zone, across every camera — for `/internal/v1/zones`."""
    result = await session.execute(select(Zone).order_by(Zone.created_at))
    return list(result.scalars().all())


async def create_zone(
    session: AsyncSession,
    *,
    camera_id: uuid.UUID,
    name: str,
    zone_type: ZoneType,
    polygon: list[tuple[float, float]],
    schedule: dict | None,
) -> Zone:
    zone = Zone(
        camera_id=camera_id, name=name, zone_type=zone_type, polygon=polygon, schedule=schedule
    )
    session.add(zone)
    await session.flush()  # populates server-generated defaults (id, created_at) for the caller
    return zone


UPDATABLE_FIELDS = frozenset({"name", "zone_type", "polygon", "schedule"})


async def update_zone(session: AsyncSession, zone: Zone, changes: dict[str, object]) -> Zone:
    """Apply exactly the fields present in `changes` (e.g.
    `ZoneUpdateRequest.model_dump(exclude_unset=True)`) — `schedule` is the
    only nullable field here, so an explicit `null` for it is a legitimate
    "clear the schedule", same reasoning as `api.adapters.cameras.update_camera`.
    """
    for field, value in changes.items():
        if field in UPDATABLE_FIELDS:
            setattr(zone, field, value)
    return zone


async def delete_zone(session: AsyncSession, zone: Zone) -> None:
    await session.delete(zone)
