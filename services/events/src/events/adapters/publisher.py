"""Sends verified events to Kafka as `event.v1` (P3-D4)."""

from __future__ import annotations

from vms_common.contracts.event import EventV1
from vms_common.kafka.producer import KafkaProducerClient


class KafkaEventPublisher:
    def __init__(self, producer: KafkaProducerClient, *, topic: str) -> None:
        self._producer = producer
        self._topic = topic

    async def publish(self, event: EventV1) -> None:
        # Keyed by camera (design §5.2) so one camera's events stay in order.
        await self._producer.send(self._topic, key=event.camera_id, message=event)
