"""Unit tests for the topology edge rules — no I/O (P3-J1)."""

from __future__ import annotations

import uuid

import pytest
from api.domain.topology import (
    MAX_TOLERANCE_S,
    MAX_TRANSIT_S,
    EdgeShape,
    find_conflict,
    validate_edge,
)

A, B, C = (uuid.uuid4() for _ in range(3))


def _ok(edge_type: str, **kw: object) -> None:
    params = {"min_s": None, "max_s": None, "tolerance_s": None, "bidirectional": False} | kw
    validate_edge(edge_type, **params)  # type: ignore[arg-type]


# --- validate_edge -----------------------------------------------------------------------


def test_a_valid_overlap_edge_passes() -> None:
    _ok("overlap", tolerance_s=3.0, bidirectional=True)
    _ok("overlap", tolerance_s=0.0, bidirectional=True)  # zero tolerance is allowed
    _ok("overlap", tolerance_s=MAX_TOLERANCE_S, bidirectional=True)


def test_a_valid_transit_edge_passes() -> None:
    _ok("transit", min_s=5.0, max_s=90.0)
    _ok("transit", min_s=5.0, max_s=90.0, bidirectional=True)
    _ok("transit", min_s=0.0, max_s=0.0)  # cameras that see the same doorway
    _ok("transit", min_s=0.0, max_s=MAX_TRANSIT_S)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tolerance_s": None, "bidirectional": True}, "needs tolerance_s"),
        ({"tolerance_s": 3.0, "bidirectional": False}, "always bidirectional"),
        ({"tolerance_s": 3.0, "bidirectional": True, "min_s": 1.0}, "not min_s/max_s"),
        ({"tolerance_s": 3.0, "bidirectional": True, "max_s": 1.0}, "not min_s/max_s"),
        ({"tolerance_s": -0.1, "bidirectional": True}, "between 0 and"),
        ({"tolerance_s": MAX_TOLERANCE_S + 1, "bidirectional": True}, "between 0 and"),
    ],
)
def test_invalid_overlap_edges_are_rejected_with_a_reason(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _ok("overlap", **kwargs)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_s": None, "max_s": 10.0}, "needs both"),
        ({"min_s": 5.0, "max_s": None}, "needs both"),
        ({"min_s": 5.0, "max_s": 10.0, "tolerance_s": 2.0}, "not tolerance_s"),
        ({"min_s": 90.0, "max_s": 5.0}, "not be below"),
        ({"min_s": -1.0, "max_s": 5.0}, "between 0 and"),
        ({"min_s": 0.0, "max_s": MAX_TRANSIT_S + 1}, "between 0 and"),
    ],
)
def test_invalid_transit_edges_are_rejected_with_a_reason(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _ok("transit", **kwargs)


# --- find_conflict -----------------------------------------------------------------------


def edge(
    kind: str,
    a: uuid.UUID,
    b: uuid.UUID,
    *,
    bidirectional: bool = False,
    id: uuid.UUID | None = None,
) -> EdgeShape:
    return EdgeShape(
        id=id or uuid.uuid4(),
        from_camera_id=a,
        to_camera_id=b,
        edge_type=kind,  # type: ignore[arg-type]
        bidirectional=bidirectional or kind == "overlap",
    )


def candidate(kind: str, a: uuid.UUID, b: uuid.UUID, *, bidirectional: bool = False) -> EdgeShape:
    return edge(kind, a, b, bidirectional=bidirectional, id=None)


def test_an_empty_graph_has_no_conflicts() -> None:
    assert find_conflict([], candidate("transit", A, B)) is None


def test_the_same_directed_pair_and_type_conflicts() -> None:
    assert "already exists" in find_conflict([edge("transit", A, B)], candidate("transit", A, B))
    assert "already exists" in find_conflict([edge("overlap", A, B)], candidate("overlap", A, B))


def test_the_same_pair_with_a_different_type_does_not_conflict() -> None:
    assert find_conflict([edge("overlap", A, B)], candidate("transit", A, B)) is None
    assert find_conflict([edge("transit", A, B)], candidate("overlap", A, B)) is None


def test_overlap_is_symmetric_so_the_reverse_direction_conflicts() -> None:
    assert "symmetric" in find_conflict([edge("overlap", A, B)], candidate("overlap", B, A))


def test_opposite_one_way_transit_edges_may_coexist() -> None:
    assert find_conflict([edge("transit", A, B)], candidate("transit", B, A)) is None


def test_a_bidirectional_transit_edge_already_covers_its_reverse() -> None:
    existing = [edge("transit", A, B, bidirectional=True)]
    assert "already covers" in find_conflict(existing, candidate("transit", B, A))


def test_a_new_bidirectional_transit_edge_would_duplicate_an_existing_reverse() -> None:
    existing = [edge("transit", A, B)]
    assert "would duplicate" in find_conflict(
        existing, candidate("transit", B, A, bidirectional=True)
    )


def test_edges_between_other_cameras_are_irrelevant() -> None:
    assert find_conflict([edge("transit", A, C)], candidate("transit", A, B)) is None
    assert find_conflict([edge("transit", C, B)], candidate("transit", B, A)) is None


def test_an_edge_being_updated_does_not_conflict_with_itself() -> None:
    mine = edge("transit", A, B)
    updated = EdgeShape(
        id=mine.id, from_camera_id=A, to_camera_id=B, edge_type="transit", bidirectional=True
    )
    assert find_conflict([mine], updated) is None
    # ...but it still conflicts with a *different* edge it would now duplicate.
    other = edge("transit", B, A)
    assert find_conflict([mine, other], updated) is not None
