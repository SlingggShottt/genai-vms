"""Round-trip tests for the correlation.v1 fixtures (style_guide.md §A.4)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.correlation import CorrelationV1
from vms_common.contracts.event import EventV1

FIXTURES = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures"


def _raw(name: str = "correlation_v1.json") -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_the_closed_fixture_round_trips() -> None:
    message = CorrelationV1.model_validate(_raw())
    assert CorrelationV1.model_validate(json.loads(message.model_dump_json())) == message
    assert (message.status, message.revision, message.max_severity) == ("closed", 3, "high")
    assert message.camera_ids == ["cam02", "cam03", "cam04"]
    assert [link.edge_type for link in message.links] == ["transit", "transit"]
    assert message.merged_into is None


def test_the_merged_fixture_points_at_the_group_that_absorbed_it() -> None:
    merged = CorrelationV1.model_validate(_raw("correlation_v1_merged.json"))
    closed = CorrelationV1.model_validate(_raw())
    assert merged.status == "merged" and merged.merged_into == closed.group_id
    assert set(merged.event_ids) <= set(closed.event_ids)  # its events live on in the survivor


def test_the_group_fixtures_agree_with_the_event_fixtures() -> None:
    events = {
        e.event_id: e
        for e in (
            EventV1.model_validate(json.loads((FIXTURES / n).read_text()))
            for n in (
                "event_v1_intrusion.json",
                "event_v1_running_skipped.json",
                "event_v1_abandoned_object.json",
            )
        )
    }
    group = CorrelationV1.model_validate(_raw())
    assert set(group.event_ids) == set(events)
    assert group.start_ts == min(e.start_ts for e in events.values())
    assert group.end_ts == max(e.end_ts for e in events.values())
    assert set(group.camera_ids) == {e.camera_id for e in events.values()}
    assert set(group.event_types) == {e.event_type for e in events.values()}
    assert group.max_severity == "high"
    for link in group.links:  # the transit delta is start(later-camera event) - end(earlier)
        a, b = events[link.from_event], events[link.to_event]
        assert link.delta_s == (b.start_ts - a.end_ts).total_seconds()


@pytest.mark.parametrize(
    "change",
    [
        {"status": "merged"},  # merged without merged_into
        {"merged_into": "0192f3e0-0002-7000-8000-00000000000b"},  # merged_into without merged
        {"status": "paused"},
        {"revision": 0},
        {"event_ids": []},
        {"camera_ids": []},
        {"group_id": "nope"},
        {"end_ts": "2026-10-05T10:00:00.000Z"},  # before start
        {"max_severity": "meh"},
        {
            "links": [
                {
                    "from_event": "0192f3d1-0001-7000-8000-000000000001",
                    "to_event": "ffffffff-ffff-7fff-8fff-ffffffffffff",
                    "edge_type": "transit",
                    "delta_s": 1.0,
                    "score": 0.9,
                }
            ]
        },
        {
            "links": [
                {
                    "from_event": "0192f3d1-0001-7000-8000-000000000001",
                    "to_event": "0192f3d1-0002-7000-8000-000000000002",
                    "edge_type": "teleport",
                    "delta_s": 1.0,
                    "score": 0.9,
                }
            ]
        },
        {
            "links": [
                {
                    "from_event": "0192f3d1-0001-7000-8000-000000000001",
                    "to_event": "0192f3d1-0002-7000-8000-000000000002",
                    "edge_type": "transit",
                    "delta_s": 1.0,
                    "score": 1.5,
                }
            ]
        },
        {"surprise": 1},
    ],
)
def test_invalid_messages_are_rejected(change: dict) -> None:
    with pytest.raises(ValidationError):
        CorrelationV1.model_validate(_raw() | change)


def test_a_group_cannot_be_merged_into_itself() -> None:
    raw = _raw("correlation_v1_merged.json")
    with pytest.raises(ValidationError):
        CorrelationV1.model_validate(raw | {"merged_into": raw["group_id"]})


def test_an_open_group_with_one_event_and_no_links_is_valid() -> None:
    raw = _raw("correlation_v1_merged.json") | {
        "status": "open",
        "merged_into": None,
        "revision": 1,
    }
    assert CorrelationV1.model_validate(raw).links == []
