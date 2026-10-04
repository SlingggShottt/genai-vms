"""Unit tests for the topology request schemas (P3-J1) — defaults per edge type and
the cross-field validation, no database."""

from __future__ import annotations

import uuid

import pytest
from api.domain.topology import DEFAULT_OVERLAP_TOLERANCE_S, MAX_TOLERANCE_S, MAX_TRANSIT_S
from api.schemas import TopologyEdgeCreateRequest, TopologyEdgeUpdateRequest
from pydantic import ValidationError

A, B = str(uuid.uuid4()), str(uuid.uuid4())


def create(**fields: object) -> TopologyEdgeCreateRequest:
    return TopologyEdgeCreateRequest.model_validate(
        {"from_camera_id": A, "to_camera_id": B} | fields
    )


def test_an_overlap_edge_defaults_to_a_five_second_two_way_tolerance() -> None:
    edge = create(edge_type="overlap")
    assert edge.tolerance_s == DEFAULT_OVERLAP_TOLERANCE_S == 5.0
    assert edge.bidirectional is True
    assert edge.min_s is None and edge.max_s is None


def test_an_overlap_edge_keeps_a_tolerance_it_was_given() -> None:
    assert create(edge_type="overlap", tolerance_s=2.5).tolerance_s == 2.5
    assert create(edge_type="overlap", tolerance_s=0).tolerance_s == 0


def test_a_transit_edge_is_one_way_unless_told_otherwise() -> None:
    assert create(edge_type="transit", min_s=5, max_s=60).bidirectional is False
    assert create(edge_type="transit", min_s=5, max_s=60, bidirectional=True).bidirectional is True


def test_camera_ids_are_normalised_to_canonical_uuids() -> None:
    upper = A.upper()
    assert create(edge_type="overlap", from_camera_id=upper).from_camera_id == A


@pytest.mark.parametrize(
    "fields",
    [
        {"edge_type": "transit"},  # no window
        {"edge_type": "transit", "min_s": 5},
        {"edge_type": "transit", "min_s": 90, "max_s": 5},
        {"edge_type": "transit", "min_s": 5, "max_s": 60, "tolerance_s": 2},
        {"edge_type": "overlap", "min_s": 5, "max_s": 60},
        {"edge_type": "overlap", "bidirectional": False},
        {"edge_type": "overlap", "tolerance_s": MAX_TOLERANCE_S + 1},
        {"edge_type": "transit", "min_s": 0, "max_s": MAX_TRANSIT_S + 1},
        {"edge_type": "transit", "min_s": -1, "max_s": 5},
        {"edge_type": "teleport"},
        {"edge_type": "overlap", "from_camera_id": "not-a-uuid"},
        {"edge_type": "overlap", "to_camera_id": A},  # a camera cannot link to itself
        {"edge_type": "overlap", "surprise": 1},
    ],
)
def test_invalid_create_requests_are_rejected(fields: dict) -> None:
    with pytest.raises(ValidationError):
        create(**fields)


def test_an_update_request_distinguishes_omitted_from_null() -> None:
    patch = TopologyEdgeUpdateRequest.model_validate({"max_s": None, "min_s": 3})
    assert patch.model_dump(exclude_unset=True) == {"max_s": None, "min_s": 3.0}
    assert TopologyEdgeUpdateRequest.model_validate({}).model_dump(exclude_unset=True) == {}


def test_an_update_request_cannot_change_an_edges_identity() -> None:
    for field in ("from_camera_id", "to_camera_id", "edge_type", "id"):
        with pytest.raises(ValidationError):
            TopologyEdgeUpdateRequest.model_validate({field: "x"})
