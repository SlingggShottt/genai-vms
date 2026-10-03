"""Round-trip tests for the event.v1 fixtures (style_guide.md §A.4)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.event import SEVERITY_ORDER, EventV1, severity_rank

FIXTURES = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures"
NAMES = [
    "event_v1_intrusion.json",
    "event_v1_running_skipped.json",
    "event_v1_abandoned_object.json",
]


def _raw(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", NAMES)
def test_event_fixtures_round_trip(name: str) -> None:
    raw = _raw(name)
    event = EventV1.model_validate(raw)
    again = json.loads(event.model_dump_json())
    # timestamps come back in a canonical ISO form; compare them as instants
    assert EventV1.model_validate(again) == event
    assert again["event_id"] == raw["event_id"] and again["camera_id"] == raw["camera_id"]


def test_the_fixtures_cover_verified_and_skipped_and_zone_and_camera_wide() -> None:
    events = [EventV1.model_validate(_raw(n)) for n in NAMES]
    assert {e.verification.status for e in events} == {"verified", "skipped"}
    assert {e.zone_id is None for e in events} == {True, False}
    skipped = next(e for e in events if e.verification.status == "skipped")
    assert skipped.verification.caption is None and skipped.verification.confidence is None


def test_the_fixture_ids_are_distinct_uuids_and_cameras_are_codes() -> None:
    events = [EventV1.model_validate(_raw(n)) for n in NAMES]
    assert len({e.event_id for e in events}) == 3
    assert [e.camera_id for e in events] == ["cam02", "cam04", "cam03"]


@pytest.mark.parametrize(
    "change",
    [
        {"event_id": "not-a-uuid"},
        {"severity": "catastrophic"},
        {"schema_version": "event.v2"},
        {"end_ts": "2026-10-05T10:15:00.000Z"},  # before start_ts
        {"start_ts": "2026-10-05T10:15:20.000"},  # naive timestamp
        {"rule_score": 1.5},
        {"keyframe_uris": ["https://example.com/frame.jpg"]},
        {"event_type": ""},
        {"verification": {"status": "rejected"}},  # rejected events are never published
        {"verification": {"status": "verified", "confidence": 2.0}},
        {"verification": {"status": "verified", "surprise": 1}},
        {"surprise": 1},
    ],
)
def test_invalid_events_are_rejected(change: dict) -> None:
    with pytest.raises(ValidationError):
        EventV1.model_validate(_raw("event_v1_intrusion.json") | change)


def test_an_event_id_is_normalised_to_canonical_form() -> None:
    raw = _raw("event_v1_intrusion.json")
    event = EventV1.model_validate(raw | {"event_id": raw["event_id"].upper()})
    assert event.event_id == raw["event_id"]


def test_a_zero_length_event_is_allowed() -> None:
    raw = _raw("event_v1_intrusion.json")
    assert EventV1.model_validate(raw | {"end_ts": raw["start_ts"]})


def test_severity_is_ordered_low_to_critical() -> None:
    assert SEVERITY_ORDER == ("low", "medium", "high", "critical")
    assert [severity_rank(s) for s in SEVERITY_ORDER] == [0, 1, 2, 3]
    with pytest.raises(ValueError):
        severity_rank("catastrophic")
