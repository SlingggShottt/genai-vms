"""Round-trip test for the zones_internal fixture (style_guide.md §A.4)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.zones import ZonesInternalResponse

FIXTURE = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures" / "zones_internal.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_zones_internal_fixture_round_trips() -> None:
    raw = _load_fixture()

    response = ZonesInternalResponse.model_validate(raw)

    assert len(response.zones) == 2
    assert response.zones[0].zone_type == "restricted"
    assert response.zones[1].schedule is not None
    assert response.zones[1].schedule.start_time == "20:00"

    dumped = json.loads(response.model_dump_json())
    assert dumped["zones"][0]["camera_id"] == raw["zones"][0]["camera_id"]


def test_zone_polygon_must_be_normalized() -> None:
    raw = _load_fixture()
    raw["zones"][0]["polygon"][0] = [1.5, 0.4]  # out of [0,1]

    with pytest.raises(ValidationError):
        ZonesInternalResponse.model_validate(raw)


def test_zone_polygon_needs_at_least_three_points() -> None:
    raw = _load_fixture()
    raw["zones"][0]["polygon"] = [[0.1, 0.1], [0.2, 0.2]]

    with pytest.raises(ValidationError):
        ZonesInternalResponse.model_validate(raw)


def test_zone_type_must_be_known() -> None:
    raw = _load_fixture()
    raw["zones"][0]["zone_type"] = "not-a-real-type"

    with pytest.raises(ValidationError):
        ZonesInternalResponse.model_validate(raw)
