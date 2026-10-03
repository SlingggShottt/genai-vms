"""Group repository — SQLAlchemy against `events.correlation_groups` / `correlation_links`.
Translates between the engine's `Group` and the rows; no linking logic lives here.

Writes are *revision-guarded upserts*: a group row is replaced only by a newer revision, so a
stale writer (a restarted instance catching up, a retried batch) can never overwrite newer
state. Links are upserted on `(from_event, to_event)` with the group re-pointed, which is how
a merge moves an absorbed group's links to the survivor without duplicating them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import CorrelationGroup, CorrelationLinkRow

from correlation.domain.types import EventRecord, Group, LinkRecord


def _member_to_json(m: EventRecord) -> dict[str, str]:
    return {
        "event_id": m.event_id,
        "site_id": m.site_id,
        "camera_id": m.camera_id,
        "event_type": m.event_type,
        "severity": m.severity,
        "start_ts": m.start_ts.isoformat(),
        "end_ts": m.end_ts.isoformat(),
    }


def _member_from_json(raw: dict[str, str]) -> EventRecord:
    return EventRecord(
        event_id=raw["event_id"],
        site_id=raw["site_id"],
        camera_id=raw["camera_id"],
        event_type=raw["event_type"],
        severity=raw["severity"],
        start_ts=datetime.fromisoformat(raw["start_ts"]),
        end_ts=datetime.fromisoformat(raw["end_ts"]),
    )


def _to_group(row: CorrelationGroup, links: list[CorrelationLinkRow]) -> Group:
    return Group(
        id=str(row.id),
        site_id=row.site_id,
        created_at=row.created_at,
        members=[_member_from_json(m) for m in row.members],
        status=row.status,  # type: ignore[arg-type]
        revision=row.revision,
        links=[
            LinkRecord(link.from_event, link.to_event, link.edge_type, link.delta_s, link.score)  # type: ignore[arg-type]
            for link in sorted(links, key=lambda x: (x.from_event, x.to_event))
        ],
        closed_at=row.closed_at,
        merged_into=str(row.merged_into) if row.merged_into else None,
        publish_pending=row.publish_pending,
        last_published_at=row.last_published_at,
    )


async def _links_by_group(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[CorrelationLinkRow]]:
    ids = list(group_ids)
    grouped: dict[uuid.UUID, list[CorrelationLinkRow]] = {gid: [] for gid in ids}
    if ids:
        rows = await session.execute(
            select(CorrelationLinkRow).where(CorrelationLinkRow.group_id.in_(ids))
        )
        for link in rows.scalars():
            grouped[link.group_id].append(link)
    return grouped


async def _load(session: AsyncSession, rows: list[CorrelationGroup]) -> list[Group]:
    links = await _links_by_group(session, (r.id for r in rows))
    return [_to_group(r, links[r.id]) for r in rows]


async def event_already_grouped(session: AsyncSession, event_id: str) -> bool:
    """Is `event_id` a member of any group — open, closed or merged? (Idempotency: Kafka
    delivers at least once, and a closed group must not take the event a second time.)"""
    found = await session.execute(
        select(CorrelationGroup.id).where(CorrelationGroup.event_ids.contains([event_id])).limit(1)
    )
    return found.first() is not None


async def load_open_groups(session: AsyncSession, *, site_id: str | None = None) -> list[Group]:
    stmt = select(CorrelationGroup).where(CorrelationGroup.status == "open")
    if site_id is not None:
        stmt = stmt.where(CorrelationGroup.site_id == site_id)
    rows = (
        await session.execute(stmt.order_by(CorrelationGroup.created_at, CorrelationGroup.id))
    ).scalars()
    return await _load(session, list(rows))


async def load_pending_groups(session: AsyncSession) -> list[Group]:
    """Groups with a change not yet announced, oldest first."""
    stmt = (
        select(CorrelationGroup)
        .where(CorrelationGroup.publish_pending)
        .order_by(CorrelationGroup.created_at, CorrelationGroup.id)
    )
    return await _load(session, list((await session.execute(stmt)).scalars()))


async def get_group(session: AsyncSession, group_id: str) -> Group | None:
    row = await session.get(CorrelationGroup, uuid.UUID(group_id))
    return None if row is None else (await _load(session, [row]))[0]


async def save_groups(session: AsyncSession, groups: Iterable[Group]) -> None:
    """Upsert groups (only where the revision is newer) and their links."""
    for group in groups:
        values = {
            "id": uuid.UUID(group.id),
            "site_id": group.site_id,
            "status": group.status,
            "revision": group.revision,
            "start_ts": group.start_ts,
            "end_ts": group.end_ts,
            "max_severity": group.max_severity,
            "camera_ids": group.camera_ids,
            "event_types": group.event_types,
            "event_ids": group.event_ids,
            "members": [_member_to_json(m) for m in group.members],
            "merged_into": uuid.UUID(group.merged_into) if group.merged_into else None,
            "publish_pending": group.publish_pending,
            "last_published_at": group.last_published_at,
            "closed_at": group.closed_at,
            "created_at": group.created_at,
        }
        stmt = insert(CorrelationGroup).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[CorrelationGroup.id],
            set_={k: stmt.excluded[k] for k in values if k not in ("id", "created_at")},
            where=CorrelationGroup.revision < stmt.excluded.revision,
        )
        await session.execute(stmt)

    # Links after every group row exists (a merged group's links point at the survivor).
    for group in groups:
        for link in group.links:
            stmt = insert(CorrelationLinkRow).values(
                id=uuid.uuid4(),
                group_id=uuid.UUID(group.id),
                from_event=link.from_event,
                to_event=link.to_event,
                edge_type=link.edge_type,
                delta_s=link.delta_s,
                score=link.score,
            )
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["from_event", "to_event"],
                    set_={"group_id": stmt.excluded.group_id},
                )
            )


async def mark_published(
    session: AsyncSession, group_id: str, *, revision: int, now: datetime
) -> None:
    """Record that `revision` of the group went out. The group stays pending if it has changed
    since (its revision is higher), so that newer state is still announced."""
    await session.execute(
        update(CorrelationGroup)
        .where(CorrelationGroup.id == uuid.UUID(group_id))
        .values(
            last_published_at=now,
            publish_pending=CorrelationGroup.revision != revision,
        )
    )
