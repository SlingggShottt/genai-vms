"""Round-trip test for the topology_internal fixture (style_guide.md §A.4)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.topology import TopologyEdgeInternal, TopologyInternalResponse

FIXTURE = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures" / "topology_internal.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _edge(**overrides: object) -> dict:
    base = {
        "id": "e1",
        "from_camera_id": "cam02",
        "to_camera_id": "cam04",
        "edge_type": "transit",
        "min_s": 5.0,
        "max_s": 90.0,
        "tolerance_s": None,
        "bidirectional": False,
    }
    return base | overrides


def test_topology_internal_fixture_round_trips() -> None:
    raw = _load_fixture()

    response = TopologyInternalResponse.model_validate(raw)

    assert [e.edge_type for e in response.edges] == ["overlap", "transit", "transit"]
    assert response.edges[0].tolerance_s == 3.0 and response.edges[0].bidirectional
    assert response.edges[1].min_s == 5.0 and response.edges[1].max_s == 90.0
    assert json.loads(response.model_dump_json()) == raw


def test_the_fixture_covers_every_edge_shape() -> None:
    edges = TopologyInternalResponse.model_validate(_load_fixture()).edges
    kinds = {(e.edge_type, e.bidirectional) for e in edges}
    assert kinds == {("overlap", True), ("transit", False), ("transit", True)}


def test_an_empty_graph_is_valid() -> None:
    assert TopologyInternalResponse.model_validate({}).edges == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"to_camera_id": "cam02"},  # self-link
        {"edge_type": "nonsense"},
        {"min_s": None},  # transit needs both bounds
        {"max_s": None},
        {"min_s": 90.0, "max_s": 5.0},  # window inverted
        {"min_s": -1.0},
        {"tolerance_s": 2.0},  # transit has no tolerance
        {
            "edge_type": "overlap",
            "min_s": None,
            "max_s": None,
            "tolerance_s": None,
            "bidirectional": True,
        },  # overlap needs a tolerance
        {
            "edge_type": "overlap",
            "tolerance_s": 2.0,
            "bidirectional": True,
        },  # overlap has no window
        {
            "edge_type": "overlap",
            "min_s": None,
            "max_s": None,
            "tolerance_s": 2.0,
            "bidirectional": False,
        },  # overlap is always two-way
        {"unknown_field": 1},
    ],
)
def test_invalid_edges_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        TopologyEdgeInternal.model_validate(_edge(**overrides))


def test_a_zero_width_transit_window_is_allowed() -> None:
    edge = TopologyEdgeInternal.model_validate(_edge(min_s=0.0, max_s=0.0))
    assert edge.min_s == edge.max_s == 0.0
