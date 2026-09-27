"""Round-trip test for segment.v1 (style_guide.md §A.4: every contract needs
>= 1 fixture and a round-trip test)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.segment import SegmentV1

FIXTURE = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures" / "segment_v1.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_segment_v1_fixture_round_trips() -> None:
    raw = _load_fixture()

    segment = SegmentV1.model_validate(raw)

    assert segment.schema_version == "segment.v1"
    assert segment.camera_id == "cam03"
    assert segment.uri.startswith("s3://vms-segments/")

    dumped = json.loads(segment.model_dump_json())
    assert dumped["segment_id"] == raw["segment_id"]
    assert dumped["camera_id"] == raw["camera_id"]
    assert dumped["uri"] == raw["uri"]


def test_segment_v1_rejects_non_s3_uri() -> None:
    raw = _load_fixture()
    raw["uri"] = "https://example.com/not-s3.ts"

    with pytest.raises(ValidationError):
        SegmentV1.model_validate(raw)


def test_segment_v1_rejects_end_before_start() -> None:
    raw = _load_fixture()
    raw["end_ts"], raw["start_ts"] = raw["start_ts"], raw["end_ts"]

    with pytest.raises(ValidationError):
        SegmentV1.model_validate(raw)


def test_segment_v1_rejects_unknown_fields() -> None:
    raw = _load_fixture()
    raw["unexpected_field"] = "not part of the contract"

    with pytest.raises(ValidationError):
        SegmentV1.model_validate(raw)


def test_segment_v1_rejects_non_positive_fps() -> None:
    raw = _load_fixture()
    raw["fps"] = 0

    with pytest.raises(ValidationError):
        SegmentV1.model_validate(raw)
