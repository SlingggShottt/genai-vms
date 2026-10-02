"""The correlation service over a real Kafka broker and Postgres (P3-J2): `event.v1` messages in,
`correlation.v1` messages out. Run via `make test-int` (needs Docker)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from correlation.adapters.publisher import KafkaCorrelationPublisher
from correlation.sweeper import Sweeper
from correlation.worker import CorrelationConsumer
from testcontainers.community.kafka import KafkaContainer
from vms_common.contracts.correlation import CorrelationV1
from vms_common.contracts.event import EventV1
from vms_common.kafka.producer import KafkaProducerClient

from .conftest import Clock  # type: ignore[import-not-found]

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def bootstrap() -> Iterator[str]:
    with KafkaContainer() as kafka:
        yield kafka.get_bootstrap_server()


@pytest.fixture
async def service(
    bootstrap, session_factory, shipped_config, fixture_topology
) -> AsyncIterator[dict]:
    """The consumer and sweeper running against fresh topics, as `main` wires them."""
    suffix = uuid.uuid4().hex[:8]
    topics = {"events": f"test-events-{suffix}", "correlations": f"test-correlations-{suffix}"}
    clock = Clock()
    lock = asyncio.Lock()
    consumer = CorrelationConsumer(
        topic=topics["events"],
        group_id=f"correlation-{suffix}",
        bootstrap_servers=bootstrap,
        model=EventV1,
        dlq_topic=f"test-dlq-{suffix}",
        session_factory=session_factory,
        get_topology=lambda: fixture_topology,
        config=shipped_config,
        lock=lock,
        clock=clock,
    )
    async with KafkaProducerClient(bootstrap_servers=bootstrap) as producer, consumer:
        sweeper = Sweeper(
            session_factory=session_factory,
            publisher=KafkaCorrelationPublisher(producer, topic=topics["correlations"]),
            get_topology=lambda: fixture_topology,
            config=shipped_config,
            lock=lock,
            interval_s=0.05,
            clock=clock,
        )
        tasks = [asyncio.create_task(consumer.run()), asyncio.create_task(sweeper.run())]
        try:
            yield {
                "topics": topics,
                "clock": clock,
                "bootstrap": bootstrap,
                "dlq": consumer._dlq_topic,
            }
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def _send(bootstrap: str, topic: str, *, key: str, value: bytes) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
    await producer.start()
    try:
        await producer.send_and_wait(topic, value=value, key=key.encode())
    finally:
        await producer.stop()


async def _read(bootstrap: str, topic: str, *, count: int, wait_s: float = 30.0) -> list:
    consumer = AIOKafkaConsumer(
        topic, bootstrap_servers=bootstrap, auto_offset_reset="earliest", group_id=None
    )
    await consumer.start()
    records = []
    try:
        async with asyncio.timeout(wait_s):
            async for record in consumer:
                records.append(record)
                if len(records) >= count:
                    break
    finally:
        await consumer.stop()
    return records


async def _read_until(bootstrap: str, topic: str, done, *, wait_s: float = 30.0) -> list:
    """Read the topic from the start until `done(messages)` holds."""
    consumer = AIOKafkaConsumer(
        topic, bootstrap_servers=bootstrap, auto_offset_reset="earliest", group_id=None
    )
    await consumer.start()
    records = []
    try:
        async with asyncio.timeout(wait_s):
            async for record in consumer:
                records.append(record)
                if done([CorrelationV1.model_validate_json(r.value) for r in records]):
                    break
    finally:
        await consumer.stop()
    return records


async def test_events_in_correlation_messages_out(service, fixtures_dir) -> None:
    topics, bootstrap, clock = service["topics"], service["bootstrap"], service["clock"]

    # a poison message first: it must go to the DLQ and not stop the consumer
    await _send(bootstrap, topics["events"], key="cam02", value=b"this is not json")
    for name in ("abandoned_object", "intrusion", "running_skipped"):
        raw = (fixtures_dir / f"event_v1_{name}.json").read_bytes()
        await _send(bootstrap, topics["events"], key=json.loads(raw)["camera_id"], value=raw)

    # The bridging event (running, cam04) merges the other two groups; the merged-away group is
    # announced as "merged" only once that has been handled — so wait for it before time passes,
    # or the groups would close before the bridge arrives.
    await _read_until(
        bootstrap, topics["correlations"], lambda ms: any(m.status == "merged" for m in ms)
    )

    clock.set(10_000)  # time passes: the surviving group can close
    records = await _read_until(
        bootstrap, topics["correlations"], lambda ms: any(m.status == "closed" for m in ms)
    )
    messages = [CorrelationV1.model_validate_json(r.value) for r in records]
    assert {r.key for r in records} == {b"rvce-campus"}  # keyed by site, one partition
    closed = [m for m in messages if m.status == "closed"]
    assert len(closed) == 1 and len(closed[0].event_ids) == 3
    assert closed[0].camera_ids == ["cam02", "cam03", "cam04"] and closed[0].max_severity == "high"
    assert any(m.status == "merged" and m.merged_into == closed[0].group_id for m in messages)

    # the poison message went to the dead-letter topic, not into the void
    dead = await _read(bootstrap, service["dlq"], count=1, wait_s=15)
    assert dead[0].value == b"this is not json"
