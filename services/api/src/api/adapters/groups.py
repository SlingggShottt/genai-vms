"""Read-only access to `events.correlation_groups` — the correlation service owns the writes
(P3-J2). The api only reads them to show an alert's group and to serve `/correlations`."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import CorrelationGroup, CorrelationLinkRow

# A group merges into a survivor that may itself merge later; a few hops is plenty, and the cap
# means a corrupt cycle ends the walk instead of looping.
MAX_MERGE_HOPS = 5


async def get_group(session: AsyncSession, group_id: uuid.UUID) -> CorrelationGroup | None:
    return await session.get(CorrelationGroup, group_id)


async def find_group_for_event(session: AsyncSession, event_id: str) -> uuid.UUID | None:
    """The live (not merged) group holding `event_id`, if correlation has placed it yet."""
    stmt = (
        select(CorrelationGroup.id)
        .where(CorrelationGroup.event_ids.contains([event_id]), CorrelationGroup.status != "merged")
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def resolve_groups(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, CorrelationGroup]:
    """Map each id to the group that holds its events now: itself, or — if it was merged — the
    survivor, following the chain. An unknown id is simply absent from the result."""
    pending = {group_id: group_id for group_id in set(group_ids)}  # asked-for id -> id to look at
    found: dict[uuid.UUID, CorrelationGroup] = {}
    for _ in range(MAX_MERGE_HOPS):
        if not pending:
            break
        rows = (
            await session.execute(
                select(CorrelationGroup).where(CorrelationGroup.id.in_(set(pending.values())))
            )
        ).scalars()
        by_id = {group.id: group for group in rows}
        following: dict[uuid.UUID, uuid.UUID] = {}
        for asked, current in pending.items():
            group = by_id.get(current)
            if group is None:
                continue
            if group.status == "merged" and group.merged_into is not None:
                following[asked] = group.merged_into
            else:
                found[asked] = group
        pending = following
    return found


async def list_groups(
    session: AsyncSession,
    *,
    limit: int,
    cursor: uuid.UUID | None,
    start: datetime | None = None,
    end: datetime | None = None,
    site_id: str | None = None,
    statuses: tuple[str, ...],
) -> list[CorrelationGroup]:
    """Newest first (uuid7 id, assigned when the group was created). A group is in the range
    when its window overlaps `[start, end)`. Merged groups are history — only their survivor
    matters — so they are left out unless asked for."""
    stmt = select(CorrelationGroup).order_by(CorrelationGroup.id.desc()).limit(limit)
    if cursor is not None:
        stmt = stmt.where(CorrelationGroup.id < cursor)
    if statuses:
        stmt = stmt.where(CorrelationGroup.status.in_(statuses))
    if site_id is not None:
        stmt = stmt.where(CorrelationGroup.site_id == site_id)
    if start is not None:
        stmt = stmt.where(CorrelationGroup.end_ts >= start)
    if end is not None:
        stmt = stmt.where(CorrelationGroup.start_ts < end)
    return list((await session.execute(stmt)).scalars().all())


async def links_for_group(session: AsyncSession, group_id: uuid.UUID) -> list[CorrelationLinkRow]:
    rows = await session.execute(
        select(CorrelationLinkRow).where(CorrelationLinkRow.group_id == group_id)
    )
    return list(rows.scalars().all())
