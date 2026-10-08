"""Integration test: BaseConsumer end-to-end against a real Kafka broker.

Run via `make test-int` (needs Docker). Covers backlog.md P1-D2: "message
produced -> consumed -> committed; poison message -> DLQ".
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import ConsumerRecord
from testcontainers.community.kafka import KafkaContainer
from vms_common.contracts.segment import SegmentV1
from vms_common.kafka.consumer import BaseConsumer

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures" / "segment_v1.json"


class _RecordingConsumer(BaseConsumer[SegmentV1]):
    """Test double that just remembers what it handled."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.handled: list[SegmentV1] = []

    async def handle(self, message: SegmentV1, record: ConsumerRecord) -> None:
        self.handled.append(message)


@pytest.fixture(scope="module")
def kafka_bootstrap_servers() -> AsyncIterator[str]:
    with KafkaContainer() as kafka:
        yield kafka.get_bootstrap_server()


async def _produce_raw(bootstrap_servers: str, topic: str, *, key: bytes, value: bytes) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
    await producer.start()
    try:
        await producer.send_and_wait(topic, value=value, key=key)
    finally:
        await producer.stop()


@pytest.mark.asyncio
async def test_valid_message_is_consumed_and_committed(kafka_bootstrap_servers: str) -> None:
    topic = f"test-segments-{uuid.uuid4().hex[:8]}"
    group = f"test-group-{uuid.uuid4().hex[:8]}"
    fixture = json.loads(FIXTURE.read_text())

    await _produce_raw(
        kafka_bootstrap_servers, topic, key=b"cam03", value=json.dumps(fixture).encode("utf-8")
    )

    consumer = _RecordingConsumer(
        topic=topic, group_id=group, bootstrap_servers=kafka_bootstrap_servers, model=SegmentV1
    )
    async with consumer:
        record = await anext(aiter(consumer._consumer))
        await consumer._process_one(record)

    assert len(consumer.handled) == 1
    assert consumer.handled[0].segment_id == fixture["segment_id"]


@pytest.mark.asyncio
async def test_poison_message_goes_to_dlq_without_retrying(kafka_bootstrap_servers: str) -> None:
    topic = f"test-poison-{uuid.uuid4().hex[:8]}"
    group = f"test-group-{uuid.uuid4().hex[:8]}"
    dlq_topic = f"test-dlq-{uuid.uuid4().hex[:8]}"

    await _produce_raw(kafka_bootstrap_servers, topic, key=b"cam03", value=b"{not valid json")

    consumer = _RecordingConsumer(
        topic=topic,
        group_id=group,
        bootstrap_servers=kafka_bootstrap_servers,
        model=SegmentV1,
        dlq_topic=dlq_topic,
    )
    async with consumer:
        record = await anext(aiter(consumer._consumer))
        await consumer._process_one(record)

    assert consumer.handled == []

    dlq_consumer = AIOKafkaConsumer(
        dlq_topic,
        bootstrap_servers=kafka_bootstrap_servers,
        group_id=f"dlq-check-{uuid.uuid4().hex[:8]}",
        auto_offset_reset="earliest",
    )
    await dlq_consumer.start()
    try:
        dlq_record = await anext(aiter(dlq_consumer))
    finally:
        await dlq_consumer.stop()

    # aiokafka hands headers back as (str, bytes) pairs
    headers = dict(dlq_record.headers)
    assert headers["x-origin-topic"].decode() == topic
    assert headers["x-attempts"].decode() == "1"  # parse failures don't retry
