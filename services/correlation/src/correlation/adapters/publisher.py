"""Where correlation messages go. A small protocol so the sweeper is tested without Kafka."""

from __future__ import annotations

from typing import Protocol

from vms_common.contracts.correlation import CorrelationV1
from vms_common.kafka.producer import KafkaProducerClient


class CorrelationPublisher(Protocol):
    async def publish(self, message: CorrelationV1) -> None: ...


class KafkaCorrelationPublisher:
    """Sends `correlation.v1` to its topic keyed by `site_id` (design_architecture.md §5.2:
    all of a site's groups land on one partition, so a consumer sees them in order)."""

    def __init__(self, producer: KafkaProducerClient, *, topic: str) -> None:
        self._producer = producer
        self._topic = topic

    async def publish(self, message: CorrelationV1) -> None:
        await self._producer.send(self._topic, key=message.site_id, message=message)
