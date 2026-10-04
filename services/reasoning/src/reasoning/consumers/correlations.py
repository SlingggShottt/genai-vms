"""Turns a closed correlation group into a reasoning job (design §8.1: "group closed &
severity ≥ threshold"), without anyone asking. Idempotent: a group that already has a live job or
a report is skipped, and a per-hour cap keeps a noisy hour from queueing a GPU for the night."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from aiokafka.structs import ConsumerRecord
from vms_common.contracts.correlation import CorrelationV1
from vms_common.contracts.event import SEVERITY_ORDER
from vms_common.kafka.consumer import BaseConsumer
from vms_common.logging import get_logger

from reasoning.adapters.store import ReasoningStore
from reasoning.settings import ReasoningSettings

log = get_logger(__name__)


class CorrelationConsumer(BaseConsumer[CorrelationV1]):
    def __init__(self, *, store: ReasoningStore, settings: ReasoningSettings) -> None:
        super().__init__(
            topic=settings.correlations_topic,
            group_id=settings.consumer_group,
            bootstrap_servers=settings.kafka.bootstrap_servers,
            model=CorrelationV1,
            dlq_topic=settings.kafka.dlq_topic,
        )
        self._store = store
        self._settings = settings

    async def handle(self, message: CorrelationV1, record: ConsumerRecord) -> None:
        s = self._settings
        if not s.auto_enabled or message.status != "closed":
            return
        if SEVERITY_ORDER.index(message.max_severity) < SEVERITY_ORDER.index(s.auto_min_severity):
            return
        age = datetime.now(UTC) - message.end_ts
        if age > timedelta(hours=6):  # replaying history must not queue a night of old work
            return
        group = uuid.UUID(message.group_id)
        if await self._store.group_has_incident(group):
            return
        since = datetime.now(UTC) - timedelta(hours=1)
        if await self._store.auto_jobs_since(since) >= s.auto_max_per_hour:
            log.info("auto_analysis_capped", group_id=message.group_id)
            return
        job = await self._store.enqueue(group_id=group, event_ids=message.event_ids, trigger="auto")
        if job:
            log.info("auto_analysis_queued", group_id=message.group_id, job_id=str(job))
