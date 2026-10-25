"""Event repository — read-only queries against `events.events` (design_architecture.md §9).

The events service owns the writes. A `rejected` row (the VLM said no) is kept for the gate's
precision figures but is not an event a person should see unless they ask for it, so the list
leaves it out unless `rejected` is among the requested statuses.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import Alert, CorrelationGroup, Event

from api.adapters.groups import resolve_groups
from api.domain.events import EventCursor

VISIBLE_BY_DEFAULT = ("verified", "skipped")


async def get_event(session: AsyncSession, event_id: uuid.UUID) -> Event | None:
    return await session.get(Event, event_id)


async def list_events(
    session: AsyncSession,
    *,
    limit: int,
    cursor: EventCursor | None,
    camera_code: str | None = None,
    event_types: Sequence[str] = (),
    severities: Sequence[str] = (),
    statuses: Sequence[str] = (),
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Event]:
    """Newest first. `start`/`end` bound the event's own `start_ts` (`start <= start_ts < end`)."""
    stmt = select(Event).order_by(Event.start_ts.desc(), Event.id.desc()).limit(limit)
    stmt = stmt.where(Event.status.in_(statuses or VISIBLE_BY_DEFAULT))
    if cursor is not None:
        stmt = stmt.where(
            or_(
                Event.start_ts < cursor.start_ts,
                and_(Event.start_ts == cursor.start_ts, Event.id < cursor.event_id),
            )
        )
    if camera_code is not None:
        stmt = stmt.where(Event.camera_id == camera_code)
    if event_types:
        stmt = stmt.where(Event.event_type.in_(event_types))
    if severities:
        stmt = stmt.where(Event.severity.in_(severities))
    if start is not None:
        stmt = stmt.where(Event.start_ts >= start)
    if end is not None:
        stmt = stmt.where(Event.start_ts < end)
    return list((await session.execute(stmt)).scalars().all())


async def groups_of_events(
    session: AsyncSession, event_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, CorrelationGroup]:
    """The correlation group holding each event now, for the events that are in one. A merged
    group is followed to its survivor, so this agrees with `GET /alerts/{id}`."""
    if not event_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT id, event_ids FROM events.correlation_groups "
                "WHERE event_ids && CAST(:ids AS text[])"
            ),
            {"ids": [str(i) for i in event_ids]},
        )
    ).all()
    group_of: dict[uuid.UUID, uuid.UUID] = {}
    for group_id, members in rows:
        for member in members:
            try:
                group_of.setdefault(uuid.UUID(member), group_id)
            except ValueError:
                continue
    survivors = await resolve_groups(session, set(group_of.values()))
    asked = set(event_ids)
    return {
        event_id: survivors[group_id]
        for event_id, group_id in group_of.items()
        if group_id in survivors and event_id in asked
    }


async def alert_ids_of_events(
    session: AsyncSession, event_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """The alert raised for each event, if its severity qualified for one."""
    if not event_ids:
        return {}
    rows = await session.execute(
        select(Alert.event_id, Alert.id).where(Alert.event_id.in_([str(i) for i in event_ids]))
    )
    return {uuid.UUID(event_id): alert_id for event_id, alert_id in rows.all()}
