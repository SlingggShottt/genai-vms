"""The crop-search request (P4-J1): one way to name the frame, and a box worth searching with."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.search import CropSearchRequest

FIXTURES = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures"
BOX = [0.1, 0.1, 0.5, 0.6]


def test_the_fixture_round_trips() -> None:
    raw = json.loads((FIXTURES / "search_crop_request.json").read_text())
    request = CropSearchRequest.model_validate(raw)
    assert request.filters.cameras == ["cam02", "cam03"] and request.top_k == 12
    assert json.loads(request.model_dump_json())["bbox"] == raw["bbox"]


@pytest.mark.parametrize(
    "frame",
    [
        {"keyframe_uri": "s3://vms-keyframes/cam02/a.jpg"},
        {"search_id": "s", "result_id": "r"},
        {"camera_id": "cam02", "at": "2026-10-25T09:30:00+00:00"},
    ],
)
def test_each_of_the_three_ways_to_name_a_frame_is_accepted(frame: dict) -> None:
    assert CropSearchRequest(bbox=BOX, **frame).bbox == BOX


@pytest.mark.parametrize(
    "frame",
    [
        {},
        {"keyframe_uri": "s3://k/a.jpg", "search_id": "s", "result_id": "r"},
        {"search_id": "s"},
        {"result_id": "r"},
        {"camera_id": "cam02"},
        {"at": "2026-10-25T09:30:00+00:00"},
        {"keyframe_uri": "s3://k/a.jpg", "camera_id": "cam02", "at": "2026-10-25T09:30:00+00:00"},
    ],
)
def test_the_frame_must_be_named_exactly_one_way_and_completely(frame: dict) -> None:
    with pytest.raises(ValidationError):
        CropSearchRequest(bbox=BOX, **frame)


@pytest.mark.parametrize(
    "box",
    [
        [0.1, 0.1, 0.1, 0.5],  # no width
        [0.1, 0.1, 0.5, 0.11],  # a sliver
        [0.5, 0.1, 0.1, 0.5],  # backwards
        [-0.1, 0.1, 0.5, 0.5],  # outside the frame
        [0.1, 0.1, 1.2, 0.5],
        [0.1, 0.1, 0.5],  # not four numbers
    ],
)
def test_a_box_that_cannot_be_searched_with_is_refused(box: list[float]) -> None:
    with pytest.raises(ValidationError):
        CropSearchRequest(bbox=box, keyframe_uri="s3://k/a.jpg")
