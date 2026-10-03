"""Consumes `event.v1`, links each event into a correlation group and persists the result
(P3-J2). The group's announcement is the sweeper's job (`sweeper.py`).

Order of effects (design §5.1 "consumers commit offsets after idempotent write"): look the
event up -> load the site's open groups -> let the engine place it -> write the changed groups
(one transaction) -> (base class) commit the offset. Redelivery is safe: a group already
holding the event ends the handler early, and the writes are revision-guarded upserts.

One lock serialises this handler with the sweeper, so a close can never interleave with a
join: this service is a single instance per consumer group (a site's events share a partition,
design §5.2; run a second replica only with a DB-level lock added).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from aiokafka.structs import ConsumerRecord
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.contracts.event import EventV1
from vms_common.kafka.consumer import BaseConsumer
from vms_common.logging import bind_context, clear_context, get_logger
from vms_db.session import session_scope

from correlation.adapters import group_repository as repo
from correlation.domain.config import CorrelationConfig
from correlation.domain.engine import add_event
from correlation.domain.topology import Topology
from correlation.domain.types import EventRecord
from correlation.metrics import events_total, links_total

log = get_logger(__name__)


def to_record(message: EventV1) -> EventRecord:
    return EventRecord(
        event_id=message.event_id,
        site_id=message.site_id,
        camera_id=message.camera_id,
        event_type=message.event_type,
        severity=message.severity,
        start_ts=message.start_ts,
        end_ts=message.end_ts,
    )


class CorrelationConsumer(BaseConsumer[EventV1]):
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        get_topology: Callable[[], Topology],
        config: CorrelationConfig,
        lock: asyncio.Lock,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._session_factory = session_factory
        self._get_topology = get_topology
        self._config = config
        self._lock = lock
        self._clock = clock

    async def handle(self, message: EventV1, record: ConsumerRecord) -> None:
        bind_context(event_id=message.event_id, camera_id=message.camera_id)
        try:
            async with self._lock:
                await self._place(message)
        finally:
            clear_context()

    async def _place(self, message: EventV1) -> None:
        async with session_scope(self._session_factory) as session:
            if await repo.event_already_grouped(session, message.event_id):
                events_total.labels(result="duplicate").inc()
                log.info("event_already_grouped")
                return
            open_groups = await repo.load_open_groups(session, site_id=message.site_id)
            outcome = add_event(
                open_groups,
                to_record(message),
                topology=self._get_topology(),
                config=self._config,
                now=self._clock(),
            )
            await repo.save_groups(session, outcome.changed)

        for link in outcome.new_links:
            links_total.labels(edge_type=link.edge_type).inc()
        merged = sum(1 for g in outcome.changed if g.status == "merged")
        result = "merged" if merged else ("joined" if outcome.new_links else "new_group")
        events_total.labels(result=result).inc()
        log.info(
            "event_grouped",
            result=result,
            group_id=outcome.group_id,
            links=len(outcome.new_links),
            merged_groups=merged,
        )
