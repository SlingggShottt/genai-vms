"""Base Kafka consumer: deserialize -> validate -> handle -> commit.

A failing message is retried with backoff (1s, 5s, 20s); after 3 failures
it is published to the DLQ topic with headers `x-origin-topic`, `x-error`,
`x-attempts`, and the offset is committed so the consumer group doesn't
get stuck (design_architecture.md §5.1, §15). A message that fails to
parse/validate at all goes straight to the DLQ (retrying won't fix a
malformed payload).

Concrete consumers subclass `BaseConsumer` and implement `handle` (an
idempotent write). Never commit an offset before that side effect is
durable (style_guide.md §A.4).
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.structs import ConsumerRecord
from pydantic import BaseModel, ValidationError

from vms_common.logging import get_logger
from vms_common.metrics import counter, gauge

log = get_logger(__name__)

# vms_kafka_consumer_lag{group,topic}: messages the group has not committed yet, summed over the
# partitions THIS process holds. With several replicas, `sum by (group, topic)` gives the total.
consumer_lag = gauge(
    "kafka", "consumer", "lag", "Messages behind the end of the topic", ("group", "topic")
)
LAG_REPORT_INTERVAL_S = 15.0
# vms_kafka_dlq_total{group,topic}: messages this group gave up on (sent to the dead-letter topic).
dead_letters = counter(
    "kafka", "dlq", "total", "Messages sent to the dead-letter topic", ("group", "topic")
)

MessageT = TypeVar("MessageT", bound=BaseModel)

RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 5.0, 20.0)
MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS)


def partition_lag(end: int, committed: int | None, beginning: int) -> int:
    """Messages between where the group is and the end of the partition. A group that has never
    committed starts at the beginning (`auto_offset_reset="earliest"`)."""
    return max(0, end - (committed if committed is not None else beginning))


async def lag_by_topic(consumer: AIOKafkaConsumer) -> dict[str, int]:
    """{topic: lag} over the partitions the consumer is assigned right now."""
    parts = list(consumer.assignment())
    if not parts:
        return {}
    ends = await consumer.end_offsets(parts)
    beginnings = await consumer.beginning_offsets(parts)
    lags: dict[str, int] = {}
    for tp in parts:
        committed = await consumer.committed(tp)
        lags[tp.topic] = lags.get(tp.topic, 0) + partition_lag(ends[tp], committed, beginnings[tp])
    return lags


class BaseConsumer(ABC, Generic[MessageT]):
    """Validate -> handle -> commit, with retry/backoff and DLQ on repeated failure."""

    def __init__(
        self,
        *,
        topic: str,
        group_id: str,
        bootstrap_servers: str,
        model: type[MessageT],
        dlq_topic: str = "vms.dlq.v1",
    ) -> None:
        self._topic = topic
        self._group_id = group_id
        self._bootstrap_servers = bootstrap_servers
        self._model = model
        self._dlq_topic = dlq_topic
        self._consumer: AIOKafkaConsumer | None = None
        self._dlq_producer: AIOKafkaProducer | None = None

    @abstractmethod
    async def handle(self, message: MessageT, record: ConsumerRecord) -> None:
        """Idempotent side effect for one validated message. Raise to retry/DLQ."""

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self._dlq_producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await self._consumer.start()
        await self._dlq_producer.start()

    async def stop(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
        if self._dlq_producer is not None:
            await self._dlq_producer.stop()

    async def __aenter__(self) -> BaseConsumer[MessageT]:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def run(self) -> None:
        """Consume forever. Call `start()` first (or use as an async context manager)."""
        if self._consumer is None:
            raise RuntimeError("call start() (or use 'async with') before run()")
        reporter = asyncio.create_task(self._report_lag())
        try:
            async for record in self._consumer:
                await self._process_one(record)
        finally:
            reporter.cancel()

    async def _report_lag(self) -> None:
        """Publish `vms_kafka_consumer_lag` every few seconds. Never fatal: a broker hiccup costs a
        data point, not the consumer."""
        while True:
            try:
                if self._consumer is not None:
                    for topic, lag in (await lag_by_topic(self._consumer)).items():
                        consumer_lag.labels(group=self._group_id, topic=topic).set(lag)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("consumer_lag_unavailable", error=str(exc))
            await asyncio.sleep(LAG_REPORT_INTERVAL_S)

    async def _process_one(self, record: ConsumerRecord) -> None:
        message, parse_error = self._parse(record)
        if parse_error is not None:
            log.warning(
                "message_validation_failed",
                topic=record.topic,
                partition=record.partition,
                offset=record.offset,
                error=str(parse_error),
            )
            await self._to_dlq(record, parse_error, attempts=1)
            await self._commit(record)
            return

        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                await self.handle(message, record)
                await self._commit(record)
                return
            except Exception as exc:
                last_error = exc
                log.warning(
                    "message_handle_failed",
                    topic=record.topic,
                    offset=record.offset,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])

        if last_error is None:  # pragma: no cover - defensive, loop always sets it
            raise RuntimeError("retry loop exited without an error to report")
        await self._to_dlq(record, last_error, attempts=MAX_ATTEMPTS)
        await self._commit(record)

    def _parse(
        self, record: ConsumerRecord
    ) -> tuple[MessageT, None] | tuple[None, ValidationError | json.JSONDecodeError]:
        try:
            payload = json.loads(record.value)
            return self._model.model_validate(payload), None
        except (json.JSONDecodeError, ValidationError) as exc:
            return None, exc

    async def _to_dlq(self, record: ConsumerRecord, error: Exception, *, attempts: int) -> None:
        if self._dlq_producer is None:
            raise RuntimeError("DLQ producer not started")
        headers = [
            ("x-origin-topic", record.topic.encode()),
            ("x-error", str(error)[:1000].encode()),
            ("x-attempts", str(attempts).encode()),
        ]
        await self._dlq_producer.send_and_wait(
            self._dlq_topic, value=record.value, key=record.key, headers=headers
        )
        dead_letters.labels(group=self._group_id, topic=record.topic).inc()
        log.error(
            "message_dead_lettered",
            topic=record.topic,
            offset=record.offset,
            attempts=attempts,
            error=str(error),
        )

    async def _commit(self, record: ConsumerRecord) -> None:
        if self._consumer is None:
            raise RuntimeError("consumer not started")
        tp = TopicPartition(record.topic, record.partition)
        await self._consumer.commit({tp: record.offset + 1})
