"""The other half of correlation: time passing (P3-J2).

Every `interval` seconds, under the same lock as the consumer:
  1. close the open groups nothing can still link to (`engine.close_due`);
  2. announce every group with an unannounced change (`engine.due_for_publish`: open groups
     throttled, closed/merged ones at once) and record that it went out.

Sending happens *after* the change is stored and `publish_pending` stays true until the send
is acknowledged, so a crash anywhere in between costs at most a duplicate message (consumers
key on `group_id` + `revision`), never a lost one. A failed sweep is logged and retried on the
next tick: the loop must outlive a Kafka or DB blip, or groups would silently stop closing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.logging import get_logger
from vms_db.session import session_scope

from correlation.adapters import group_repository as repo
from correlation.adapters.publisher import CorrelationPublisher
from correlation.domain.config import CorrelationConfig
from correlation.domain.engine import close_due, due_for_publish, to_message
from correlation.domain.topology import Topology
from correlation.metrics import (
    groups_closed_total,
    open_groups,
    published_total,
    sweep_errors_total,
)

log = get_logger(__name__)


class Sweeper:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        publisher: CorrelationPublisher,
        get_topology: Callable[[], Topology],
        config: CorrelationConfig,
        lock: asyncio.Lock,
        interval_s: float = 1.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._get_topology = get_topology
        self._config = config
        self._lock = lock
        self._interval_s = interval_s
        self._clock = clock

    async def run(self) -> None:
        while True:
            try:
                await self.sweep()
            except Exception as exc:  # noqa: BLE001 - one bad sweep must not end the loop
                sweep_errors_total.inc()
                log.warning("sweep_failed", error=repr(exc))
            await asyncio.sleep(self._interval_s)

    async def sweep(self) -> None:
        """One pass: close what is due, then announce what changed."""
        async with self._lock:
            now = self._clock()
            async with session_scope(self._session_factory) as session:
                still_open = await repo.load_open_groups(session)
                closed = close_due(
                    still_open, topology=self._get_topology(), config=self._config, now=now
                )
                await repo.save_groups(session, closed)
            for group in closed:
                groups_closed_total.inc()
                log.info("group_closed", group_id=group.id, events=len(group.members))
            open_groups.set(len(still_open) - len(closed))

            async with session_scope(self._session_factory) as session:
                pending = await repo.load_pending_groups(session)
            for group in due_for_publish(pending, config=self._config, now=now):
                revision = group.revision
                await self._publisher.publish(to_message(group))
                async with session_scope(self._session_factory) as session:
                    await repo.mark_published(session, group.id, revision=revision, now=now)
                published_total.labels(status=group.status).inc()
                log.info(
                    "group_published", group_id=group.id, status=group.status, revision=revision
                )
