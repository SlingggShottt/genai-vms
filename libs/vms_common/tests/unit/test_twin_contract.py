"""Round-trip test for twin.v1 and twinready.v1 (style_guide.md §A.4)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.twin import TwinV1
from vms_common.contracts.twinready import TwinReadyV1

FIXTURES = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_twin_v1_fixture_round_trips() -> None:
    raw = _load("twin_v1.json")

    twin = TwinV1.model_validate(raw)

    assert twin.schema_version == "twin.v1"
    assert twin.camera_id == "cam03"
    assert len(twin.frames) == 1
    assert twin.frames[0].objects[0].track_id == "cam03-t412"
    assert twin.tracks[0].best_crop_uri.startswith("s3://vms-crops/")

    dumped = json.loads(twin.model_dump_json())
    assert dumped["segment_id"] == raw["segment_id"]


def test_twin_v1_rejects_unnormalized_bbox() -> None:
    raw = _load("twin_v1.json")
    raw["frames"][0]["objects"][0]["bbox"] = [0.5, 0.5, 1.5, 0.9]  # x2 > 1

    with pytest.raises(ValidationError):
        TwinV1.model_validate(raw)


def test_twin_v1_rejects_inverted_bbox() -> None:
    raw = _load("twin_v1.json")
    raw["frames"][0]["objects"][0]["bbox"] = [0.5, 0.5, 0.4, 0.9]  # x1 > x2

    with pytest.raises(ValidationError):
        TwinV1.model_validate(raw)


def test_twin_v1_rejects_non_s3_keyframe_uri() -> None:
    raw = _load("twin_v1.json")
    raw["frames"][0]["keyframe_uri"] = "https://example.com/frame.jpg"

    with pytest.raises(ValidationError):
        TwinV1.model_validate(raw)


def test_twinready_v1_fixture_round_trips() -> None:
    raw = _load("twinready_v1.json")

    message = TwinReadyV1.model_validate(raw)

    assert message.schema_version == "twinready.v1"
    assert message.twin_uri.startswith("s3://vms-twins/")
    assert message.counts == {"person": 4, "backpack": 1}

    dumped = json.loads(message.model_dump_json())
    assert dumped["segment_id"] == raw["segment_id"]


def test_twinready_v1_rejects_end_before_start() -> None:
    raw = _load("twinready_v1.json")
    raw["end_ts"], raw["start_ts"] = raw["start_ts"], raw["end_ts"]

    with pytest.raises(ValidationError):
        TwinReadyV1.model_validate(raw)


def test_twinready_v1_rejects_non_s3_uri() -> None:
    raw = _load("twinready_v1.json")
    raw["twin_uri"] = "https://example.com/twin.json"

    with pytest.raises(ValidationError):
        TwinReadyV1.model_validate(raw)
