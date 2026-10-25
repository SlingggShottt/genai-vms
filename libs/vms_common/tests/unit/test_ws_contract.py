"""Round-trip test for the WebSocket messages the reasoning service publishes (style_guide §A.4)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.ws import (
    INCIDENT_READY,
    JOB_PROGRESS,
    WS_CHANNEL,
    IncidentReadyData,
    JobProgressData,
    WsMessage,
    incident_ready,
    job_progress,
)

FIXTURES = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_the_job_progress_fixture_round_trips() -> None:
    raw = _load("ws_job_progress.json")
    message = WsMessage.model_validate(raw)
    assert message.type == JOB_PROGRESS == "job.progress"
    data = JobProgressData.model_validate(message.data)
    assert (data.status, data.fraction, data.stage) == ("running", 0.45, "reading action · cam02")
    assert json.loads(message.to_json())["data"] == raw["data"]


def test_the_incident_ready_fixture_round_trips() -> None:
    raw = _load("ws_incident_ready.json")
    message = WsMessage.model_validate(raw)
    assert message.type == INCIDENT_READY == "incident.ready"
    data = IncidentReadyData.model_validate(message.data)
    assert (data.status, data.severity) == ("generated", "high")
    assert json.loads(message.to_json())["data"] == raw["data"]


def _same_message(built: WsMessage, raw: dict) -> bool:
    """Equal as messages: the timestamp compared as a time (pydantic writes microseconds)."""
    return built == WsMessage.model_validate(raw)


def test_the_builders_make_the_same_message_as_the_fixture() -> None:
    raw = _load("ws_job_progress.json")
    at = datetime(2026, 10, 25, 10, 16, 14, 512000, tzinfo=UTC)
    assert _same_message(job_progress(JobProgressData.model_validate(raw["data"]), ts=at), raw)
    raw = _load("ws_incident_ready.json")
    at = datetime(2026, 10, 25, 10, 17, 2, 101000, tzinfo=UTC)
    assert _same_message(incident_ready(IncidentReadyData.model_validate(raw["data"]), ts=at), raw)


def test_a_builder_does_not_make_a_different_message_by_accident() -> None:
    raw = _load("ws_job_progress.json")
    at = datetime(2026, 10, 25, 10, 16, 14, 512000, tzinfo=UTC)
    other = {**raw["data"], "stage": "something else"}
    assert not _same_message(job_progress(JobProgressData.model_validate(other), ts=at), raw)
    assert not _same_message(
        job_progress(JobProgressData.model_validate(raw["data"]), ts=at.replace(microsecond=0)), raw
    )


def test_a_message_without_a_timestamp_gets_one_in_utc() -> None:
    message = job_progress(JobProgressData(job_id="j", status="done", stage="done", fraction=1.0))
    assert message.ts.tzinfo is not None and message.ts.utcoffset().total_seconds() == 0


def test_the_channel_is_the_one_the_api_relay_listens_on() -> None:
    from api.realtime.relay import CHANNEL

    assert CHANNEL == WS_CHANNEL == "vms:ws:broadcast"


@pytest.mark.parametrize("fraction", [-0.1, 1.01])
def test_progress_outside_zero_to_one_is_rejected(fraction: float) -> None:
    with pytest.raises(ValidationError):
        JobProgressData(job_id="j", status="running", stage="s", fraction=fraction)


def test_an_unknown_status_or_severity_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JobProgressData(job_id="j", status="paused", stage="s", fraction=0.5)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        IncidentReadyData(incident_id="i", status="generated", severity="urgent", title="t")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        IncidentReadyData(incident_id="i", status="pending", severity="low", title="t")  # type: ignore[arg-type]


def test_extra_fields_and_a_naive_timestamp_are_rejected() -> None:
    with pytest.raises(ValidationError):
        JobProgressData.model_validate({**_load("ws_job_progress.json")["data"], "x": 1})
    with pytest.raises(ValidationError):
        WsMessage.model_validate({**_load("ws_job_progress.json"), "ts": "2026-10-25T10:16:14"})
