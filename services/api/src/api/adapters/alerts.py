"""Alert repository — SQLAlchemy queries against `core.alerts` (P3-J3). No business rules here
(which events qualify, who may act); the lifecycle moves are single conditional UPDATEs, so two
operators acting at once cannot both win.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import Alert, CorrelationGroup

from api.domain.alerts import AlertDraft


async def get_alert(session: AsyncSession, alert_id: uuid.UUID) -> Alert | None:
    return await session.get(Alert, alert_id)


async def create_if_absent(
    session: AsyncSession, draft: AlertDraft, *, group_id: uuid.UUID | None
) -> Alert | None:
    """Insert the alert for `draft`; `None` if its event already has one (a redelivered
    `event.v1`). The unique `event_id` decides, not a prior SELECT, so two consumers racing on
    the same event still produce exactly one alert."""
    stmt = (
        pg_insert(Alert)
        .values(
            event_id=draft.event_id,
            site_id=draft.site_id,
            camera_id=draft.camera_id,
            event_type=draft.event_type,
            severity=draft.severity,
            rule_id=draft.rule_id,
            zone_id=draft.zone_id,
            title=draft.title,
            caption=draft.caption,
            verification_status=draft.verification_status,
            confidence=draft.confidence,
            start_ts=draft.start_ts,
            end_ts=draft.end_ts,
            keyframe_uris=draft.keyframe_uris,
            group_id=group_id,
        )
        .on_conflict_do_nothing(index_elements=[Alert.event_id])
        .returning(Alert)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_alerts(
    session: AsyncSession,
    *,
    limit: int,
    cursor: uuid.UUID | None,
    statuses: Sequence[str] = (),
    severities: Sequence[str] = (),
    camera_code: str | None = None,
    group_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Alert]:
    """Newest first, cursor pagination on `id` (uuid7 is time-ordered; same convention as
    cameras). `start`/`end` bound the event's own `start_ts` (`start <= start_ts < end`)."""
    stmt = select(Alert).order_by(Alert.id.desc()).limit(limit)
    if cursor is not None:
        stmt = stmt.where(Alert.id < cursor)
    if statuses:
        stmt = stmt.where(Alert.status.in_(statuses))
    if severities:
        stmt = stmt.where(Alert.severity.in_(severities))
    if camera_code is not None:
        stmt = stmt.where(Alert.camera_id == camera_code)
    if group_id is not None:
        stmt = stmt.where(Alert.group_id == group_id)
    if start is not None:
        stmt = stmt.where(Alert.start_ts >= start)
    if end is not None:
        stmt = stmt.where(Alert.start_ts < end)
    return list((await session.execute(stmt)).scalars().all())


async def acknowledge(
    session: AsyncSession, alert_id: uuid.UUID, *, user_id: uuid.UUID, note: str | None
) -> Alert | None:
    """open -> acknowledged. `None` when there is no such alert *or* it is no longer open;
    the caller tells the two apart with `get_alert`."""
    stmt = (
        update(Alert)
        .where(Alert.id == alert_id, Alert.status == "open")
        .values(
            status="acknowledged",
            acknowledged_by=user_id,
            acknowledged_at=func.now(),
            ack_note=note,
        )
        .returning(Alert)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def resolve(
    session: AsyncSession, alert_id: uuid.UUID, *, user_id: uuid.UUID, note: str | None
) -> Alert | None:
    """open|acknowledged -> resolved (a false alarm needs no acknowledgement first). `None`
    when there is no such alert or it is already resolved."""
    stmt = (
        update(Alert)
        .where(Alert.id == alert_id, Alert.status.in_(("open", "acknowledged")))
        .values(status="resolved", resolved_by=user_id, resolved_at=func.now(), resolve_note=note)
        .returning(Alert)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_group_for_events(
    session: AsyncSession, event_ids: Sequence[str], group_id: uuid.UUID
) -> list[Alert]:
    """Point the alerts of `event_ids` at `group_id`; returns only those that changed.

    Guarded against a stale message: nothing is set unless the group is, in the database
    (which correlation writes *before* it announces), not merged — so an old `open` message
    arriving after the `merged` one cannot undo the merge."""
    live = select(CorrelationGroup.id).where(
        CorrelationGroup.id == group_id, CorrelationGroup.status != "merged"
    )
    stmt = (
        update(Alert)
        .where(
            Alert.event_id.in_(list(event_ids)),
            Alert.group_id.is_distinct_from(group_id),
            live.exists(),
        )
        .values(group_id=group_id)
        .returning(Alert)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    return list((await session.execute(stmt)).scalars().all())


async def repoint_group(
    session: AsyncSession, *, from_group: uuid.UUID, into_group: uuid.UUID, event_ids: Sequence[str]
) -> list[Alert]:
    """A group was merged into another: its alerts follow. Matches by the old group id *and*
    by event id, so an alert whose group was never recorded still lands in the survivor."""
    stmt = (
        update(Alert)
        .where(
            (Alert.group_id == from_group) | Alert.event_id.in_(list(event_ids)),
            Alert.group_id.is_distinct_from(into_group),
        )
        .values(group_id=into_group)
        .returning(Alert)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    return list((await session.execute(stmt)).scalars().all())
