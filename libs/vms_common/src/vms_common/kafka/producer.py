"""Async Kafka producer wrapper: validates message size, sends JSON.

Kafka carries metadata only (design_architecture.md §5.1); video/keyframe
bytes go to object storage and travel as `s3://` URIs instead.
"""

from __future__ import annotations

from aiokafka import AIOKafkaProducer
from pydantic import BaseModel

from vms_common.logging import get_logger

log = get_logger(__name__)

MAX_MESSAGE_BYTES = 1_000_000  # CLAUDE.md hard rule: "stay under 1 MB"


class MessageTooLargeError(ValueError):
    """Raised when a serialized message would exceed MAX_MESSAGE_BYTES."""


class KafkaProducerClient:
    """Thin wrapper over `aiokafka.AIOKafkaProducer` for one bootstrap cluster."""

    def __init__(self, *, bootstrap_servers: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def __aenter__(self) -> KafkaProducerClient:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def send(self, topic: str, *, key: str, message: BaseModel) -> None:
        """Serialize `message` to JSON and send it, keyed by `key` (e.g. camera_id)."""
        if self._producer is None:
            raise RuntimeError("call start() (or use 'async with') before send()")

        payload = message.model_dump_json().encode("utf-8")
        if len(payload) > MAX_MESSAGE_BYTES:
            raise MessageTooLargeError(
                f"message for topic {topic!r} is {len(payload)} bytes "
                f"(limit {MAX_MESSAGE_BYTES}); put large data in object storage instead"
            )
        await self._producer.send_and_wait(topic, value=payload, key=key.encode("utf-8"))
        log.debug("message_sent", topic=topic, key=key, bytes=len(payload))
