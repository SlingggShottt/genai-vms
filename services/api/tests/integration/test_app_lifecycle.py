"""Starting and stopping the app with its background work (P3-J3): shutdown must be prompt and
clean, and a Kafka that is not there must not take the HTTP API down. Run via `make test-int`."""

from __future__ import annotations

import json
import time

import pytest
from api.main import create_app
from api.settings import AlertSettings, ApiSettings
from fastapi.testclient import TestClient
from vms_common.config import KafkaSettings

pytestmark = pytest.mark.integration


def logged_events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    """The structured log events the app emitted (it logs JSON through the stdlib once
    `configure_logging` has run in the process, which an app start always does)."""
    events = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except ValueError:
            continue
        if isinstance(payload, dict) and "event" in payload:
            events.append(payload)
    return events


def test_the_app_stops_promptly_even_when_stopped_straight_after_starting(
    api_settings: ApiSettings, caplog: pytest.LogCaptureFixture
) -> None:
    """A cancel that lands while the relay is still connecting used to be lost inside redis-py:
    the relay listened on for ever and shutdown waited out its grace period (or hung)."""
    for _ in range(8):
        started = time.monotonic()
        with TestClient(create_app(api_settings)) as client:
            unauthenticated = client.get("/api/v1/alerts")  # a request, then straight out
        assert unauthenticated.status_code == 401
        assert time.monotonic() - started < 3.5
    stuck = [e for e in logged_events(caplog) if e["event"] == "background_task_did_not_stop"]
    assert stuck == []


def test_the_api_serves_requests_while_kafka_is_unreachable_and_still_shuts_down(
    api_settings: ApiSettings, caplog: pytest.LogCaptureFixture
) -> None:
    settings = api_settings.model_copy(
        update={
            "kafka": KafkaSettings(bootstrap_servers="127.0.0.1:1"),  # nothing listens here
            "alerts": AlertSettings(_env_file=None, consumers_enabled=True),
        }
    )
    started = time.monotonic()
    with TestClient(create_app(settings)) as client:
        time.sleep(1.5)  # long enough for the supervisors to fail and begin backing off
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/alerts").status_code == 401
    assert time.monotonic() - started < 10
    events = logged_events(caplog)
    failed = [e for e in events if e["event"] == "consumer_failed"]
    assert {e["consumer"] for e in failed} == {"alerts-events", "alerts-correlations"}
    assert [e for e in events if e["event"] == "background_task_did_not_stop"] == []


def test_with_consumers_disabled_no_consumer_runs(
    api_settings: ApiSettings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    with TestClient(create_app(api_settings)):
        time.sleep(0.5)
    events = logged_events(caplog)
    assert [e for e in events if e["event"].startswith("consumer_")] == []
    assert any(e["event"] == "api_started" and e["alert_consumers"] is False for e in events)
