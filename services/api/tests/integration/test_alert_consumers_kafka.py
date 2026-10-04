"""The whole alerting path over a real Kafka broker, Postgres and Redis (P3-J3): an `event.v1`
message in -> an alert in the database, on the REST API and pushed to a WebSocket; a
`correlation.v1` message -> the alert's group. Run via `make test-int` (needs Docker)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from api.main import create_app
from api.settings import AlertSettings, ApiSettings
from fastapi.testclient import TestClient
from testcontainers.community.kafka import KafkaContainer
from vms_common.config import KafkaSettings
from vms_db.models import CorrelationGroup

pytestmark = pytest.mark.integration

Headers = Callable[[str], dict[str, str]]
SeedGroup = Callable[..., Awaitable[CorrelationGroup]]


@pytest.fixture(scope="module")
def bootstrap() -> Iterator[str]:
    with KafkaContainer() as kafka:
        yield kafka.get_bootstrap_server()


@pytest.fixture
def topics() -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return {
        "events": f"test-events-{suffix}",
        "correlations": f"test-correlations-{suffix}",
        "dlq": f"test-dlq-{suffix}",
        "suffix": suffix,
    }


@pytest.fixture
def kafka_client(
    api_settings: ApiSettings, bootstrap: str, topics: dict[str, str]
) -> Iterator[TestClient]:
    """The app with its alert consumers switched on, reading private topics."""
    settings = api_settings.model_copy(
        update={
            "kafka": KafkaSettings(bootstrap_servers=bootstrap, dlq_topic=topics["dlq"]),
            "alerts": AlertSettings(
                _env_file=None,
                consumers_enabled=True,
                events_topic=topics["events"],
                correlations_topic=topics["correlations"],
                events_group=f"api-alerts-{topics['suffix']}",
                correlations_group=f"api-alerts-correlations-{topics['suffix']}",
            ),
        }
    )
    with TestClient(create_app(settings)) as client:
        yield client


async def send(bootstrap: str, topic: str, *, key: str, value: bytes) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
    await producer.start()
    try:
        await producer.send_and_wait(topic, value=value, key=key.encode())
    finally:
        await producer.stop()


def fresh_event(fixtures_dir: Path, camera: str, **over: Any) -> dict[str, Any]:
    """The intrusion fixture, made unique and recent (so it is announced, not 'stale')."""
    raw = json.loads((fixtures_dir / "event_v1_intrusion.json").read_text())
    now = datetime.now(UTC)
    raw.update(
        event_id=str(uuid.uuid4()),
        camera_id=camera,
        start_ts=(now - timedelta(seconds=22)).isoformat(),
        end_ts=(now - timedelta(seconds=2)).isoformat(),
    )
    raw.update(over)
    return raw


def wait_for(fn: Callable[[], Any], *, what: str, wait_s: float = 45.0) -> Any:
    import time  # noqa: PLC0415

    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        found = fn()
        if found:
            return found
        time.sleep(0.25)
    pytest.fail(f"timed out waiting for {what}")


def receive(ws: Any, wait_s: float = 45.0) -> dict[str, Any]:
    """`receive_json` blocks for ever; bound it so a broken pipeline fails instead of hanging."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ws.receive_json).result(timeout=wait_s)


def alerts_on(client: TestClient, token: str, camera: str, headers: Headers) -> list[dict]:
    response = client.get("/api/v1/alerts", params={"camera_id": camera}, headers=headers(token))
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def test_an_event_message_becomes_an_alert_pushed_to_the_dashboard(
    kafka_client: TestClient,
    bootstrap: str,
    topics: dict[str, str],
    fixtures_dir: Path,
    make_user: Callable[[str], dict[str, str]],
    auth_headers: Headers,
    unique_camera: str,
) -> None:
    operator = make_user("operator")
    event = fresh_event(fixtures_dir, unique_camera)
    with kafka_client.websocket_connect(f"/api/v1/ws?token={operator['token']}") as ws:
        wait_for(
            lambda: (
                kafka_client.app.state.relay.ready.is_set()
                and kafka_client.app.state.hub.connection_count == 1
            ),
            what="the websocket to be registered",
        )

        await send(bootstrap, topics["events"], key=unique_camera, value=json.dumps(event).encode())

        pushed = receive(ws)

    assert pushed["type"] == "alert.created"
    assert pushed["data"]["event_id"] == event["event_id"]
    assert pushed["data"]["camera_code"] == unique_camera
    assert pushed["data"]["severity"] == "high" and pushed["data"]["status"] == "open"
    assert pushed["data"]["title"] == f"Intrusion on {unique_camera}"
    assert pushed["data"]["keyframe_urls"] == [] and pushed["data"]["keyframe_count"] == 2
    (listed,) = alerts_on(kafka_client, operator["token"], unique_camera, auth_headers)
    assert listed["id"] == pushed["data"]["id"] and len(listed["keyframe_urls"]) == 2


async def test_redelivery_and_poison_messages_do_not_stop_alerting(
    kafka_client: TestClient,
    bootstrap: str,
    topics: dict[str, str],
    fixtures_dir: Path,
    make_user: Callable[[str], dict[str, str]],
    auth_headers: Headers,
    unique_camera: str,
) -> None:
    operator = make_user("operator")
    first = fresh_event(fixtures_dir, unique_camera)
    second = fresh_event(fixtures_dir, unique_camera)

    await send(bootstrap, topics["events"], key=unique_camera, value=b"this is not json")
    await send(bootstrap, topics["events"], key=unique_camera, value=json.dumps(first).encode())
    await send(
        bootstrap, topics["events"], key=unique_camera, value=json.dumps(first).encode()
    )  # again
    await send(bootstrap, topics["events"], key=unique_camera, value=json.dumps(second).encode())

    items = wait_for(
        lambda: (
            found
            if len(found := alerts_on(kafka_client, operator["token"], unique_camera, auth_headers))
            >= 2
            else None
        ),
        what="both distinct events to become alerts",
    )
    await asyncio.sleep(1.5)  # long enough for a wrongly-created duplicate to appear
    items = alerts_on(kafka_client, operator["token"], unique_camera, auth_headers)
    assert sorted(a["event_id"] for a in items) == sorted([first["event_id"], second["event_id"]])

    dead = AIOKafkaConsumer(
        topics["dlq"], bootstrap_servers=bootstrap, auto_offset_reset="earliest", group_id=None
    )
    await dead.start()
    try:
        async with asyncio.timeout(30):
            record = await dead.getone()
    finally:
        await dead.stop()
    headers = dict(record.headers)
    assert record.value == b"this is not json"
    assert headers["x-origin-topic"] == topics["events"].encode()


async def test_a_correlation_message_puts_the_alert_in_its_group_and_updates_the_dashboard(
    kafka_client: TestClient,
    bootstrap: str,
    topics: dict[str, str],
    fixtures_dir: Path,
    make_user: Callable[[str], dict[str, str]],
    auth_headers: Headers,
    seed_group: SeedGroup,
    unique_camera: str,
) -> None:
    operator = make_user("operator")
    event = fresh_event(fixtures_dir, unique_camera)
    with kafka_client.websocket_connect(f"/api/v1/ws?token={operator['token']}") as ws:
        wait_for(
            lambda: (
                kafka_client.app.state.relay.ready.is_set()
                and kafka_client.app.state.hub.connection_count == 1
            ),
            what="the websocket to be registered",
        )
        await send(bootstrap, topics["events"], key=unique_camera, value=json.dumps(event).encode())
        assert receive(ws)["type"] == "alert.created"

        group = await seed_group(event_ids=[event["event_id"]], cameras=(unique_camera,))
        message = json.loads((fixtures_dir / "correlation_v1.json").read_text())
        message.update(
            group_id=str(group.id),
            status="open",
            revision=1,
            event_ids=[event["event_id"]],
            camera_ids=[unique_camera],
            event_types=["intrusion"],
            links=[],
            merged_into=None,
        )
        await send(
            bootstrap, topics["correlations"], key="rvce-campus", value=json.dumps(message).encode()
        )

        updated = receive(ws)

    assert updated["type"] == "alert.updated"
    assert updated["data"]["event_id"] == event["event_id"]
    assert updated["data"]["group"]["id"] == str(group.id)
    (listed,) = alerts_on(kafka_client, operator["token"], unique_camera, auth_headers)
    assert listed["group"]["id"] == str(group.id) and listed["group"]["event_count"] == 1
