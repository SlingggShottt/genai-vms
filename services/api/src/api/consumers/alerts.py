"""The api's two Kafka consumers (P3-J3): `event.v1` -> alerts, `correlation.v1` -> alert groups.

Both follow validate -> idempotent write -> commit (the base class commits after `handle`
returns). Neither lets a notification or a push decide the outcome: those happen *after* the
database commit and cannot raise into the base class's retry, which would otherwise replay a
message whose effect is already stored.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from aiokafka.structs import ConsumerRecord
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.contracts.correlation import CorrelationV1
from vms_common.contracts.event import EventV1
from vms_common.kafka.consumer import BaseConsumer
from vms_common.logging import bind_context, clear_context, get_logger
from vms_db.models import Alert
from vms_db.session import session_scope

from api.adapters.alert_views import build_alert_outs
from api.adapters.alerts import create_if_absent, repoint_group, set_group_for_events
from api.adapters.groups import find_group_for_event
from api.domain.alerts import draft_from_event, is_fresh, should_alert
from api.metrics import (
    alert_announcements_skipped_total,
    alerts_created_total,
    alerts_skipped_total,
)
from api.notifiers import AlertNotice, NotificationDispatcher
from api.realtime.messages import WsMessage
from api.realtime.publish import publish_best_effort
from api.realtime.relay import RedisRelay
from api.schemas import AlertOut

log = get_logger(__name__)


def notice_from(out: AlertOut) -> AlertNotice:
    return AlertNotice(
        alert_id=out.id,
        title=out.title,
        severity=out.severity,
        event_type=out.event_type,
        camera_code=out.camera_code,
        caption=out.caption,
        start_ts=out.start_ts,
        payload=out.model_dump(mode="json"),
    )


class AlertEventConsumer(BaseConsumer[EventV1]):
    """One alert per verified event at or above `min_severity`; a redelivered event adds none."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        dispatcher: NotificationDispatcher,
        min_severity: str,
        notify_max_age_s: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        **kwargs: object,
    ) -> None:
        super().__init__(model=EventV1, **kwargs)  # type: ignore[arg-type]
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._min_severity = min_severity
        self._notify_max_age_s = notify_max_age_s
        self._clock = clock

    async def handle(self, message: EventV1, record: ConsumerRecord) -> None:
        bind_context(event_id=message.event_id, camera_id=message.camera_id)
        try:
            out = await self._store(message)
            if out is None:
                return
            if not is_fresh(out.end_ts, now=self._clock(), max_age_s=self._notify_max_age_s):
                alert_announcements_skipped_total.labels(reason="stale").inc()
                log.info("alert_not_announced_stale", alert_id=out.id)
                return
            # After the commit: a slow or failing channel can neither undo nor repeat it.
            await self._dispatcher.dispatch(notice_from(out))
        finally:
            clear_context()

    async def _store(self, message: EventV1) -> AlertOut | None:
        if not should_alert(message.severity, self._min_severity):
            alerts_skipped_total.labels(reason="below_threshold").inc()
            return None
        draft = draft_from_event(message)
        async with session_scope(self._session_factory) as session:
            group_id = await find_group_for_event(session, draft.event_id)
            alert = await create_if_absent(session, draft, group_id=group_id)
            if alert is None:
                alerts_skipped_total.labels(reason="duplicate").inc()
                log.info("alert_already_exists")
                return None
            (out,) = await build_alert_outs(session, [alert])
        alerts_created_total.labels(severity=out.severity).inc()
        log.info("alert_created", alert_id=out.id, severity=out.severity, group_id=group_id)
        return out


class AlertGroupConsumer(BaseConsumer[CorrelationV1]):
    """Keeps each alert's `group_id` in step with correlation, and tells the dashboards."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        relay: RedisRelay,
        **kwargs: object,
    ) -> None:
        super().__init__(model=CorrelationV1, **kwargs)  # type: ignore[arg-type]
        self._session_factory = session_factory
        self._relay = relay

    async def handle(self, message: CorrelationV1, record: ConsumerRecord) -> None:
        bind_context(group_id=message.group_id, group_status=message.status)
        try:
            outs = await self._apply(message)
            for out in outs:
                await publish_best_effort(
                    self._relay, WsMessage(type="alert.updated", data=out.model_dump(mode="json"))
                )
        finally:
            clear_context()

    async def _apply(self, message: CorrelationV1) -> list[AlertOut]:
        group_id = uuid.UUID(message.group_id)
        async with session_scope(self._session_factory) as session:
            changed: list[Alert]
            if message.status == "merged":
                # `merged_into` is guaranteed by the contract's validator.
                changed = await repoint_group(
                    session,
                    from_group=group_id,
                    into_group=uuid.UUID(message.merged_into or ""),
                    event_ids=message.event_ids,
                )
            else:
                changed = await set_group_for_events(session, message.event_ids, group_id)
            outs = await build_alert_outs(session, changed)
        if outs:
            log.info("alert_groups_updated", alerts=len(outs))
        return outs
