"""The engine's view of the camera graph."""

from __future__ import annotations

from correlation.domain.topology import Topology


def test_edges_between_finds_an_edge_in_either_direction(edge) -> None:
    ab = edge("A", "B")
    topo = Topology([ab, edge("B", "C")])
    assert topo.edges_between("A", "B") == [ab]
    assert topo.edges_between("B", "A") == [ab]
    assert topo.edges_between("A", "C") == []


def test_several_edges_may_join_the_same_pair(edge) -> None:
    transit, overlap = edge("A", "B"), edge("A", "B", "overlap")
    assert Topology([transit, overlap]).edges_between("B", "A") == [transit, overlap]


def test_max_window_is_the_longest_transit_or_twice_the_overlap_tolerance(edge) -> None:
    topo = Topology(
        [
            edge("A", "B", max_s=40),
            edge("A", "C", max_s=75),
            edge("D", "E", "overlap", tolerance_s=50),  # 2 x 50 = 100
            edge("F", "G", max_s=500),  # unrelated cameras
        ]
    )
    assert topo.max_window_s(["A"]) == 75  # A touches the 40 and the 75
    assert topo.max_window_s(["B"]) == 40
    assert topo.max_window_s(["D"]) == 100
    assert topo.max_window_s(["A", "D"]) == 100
    assert topo.max_window_s(["A", "B", "C"]) == 75


def test_a_camera_without_edges_has_no_window(edge) -> None:
    assert Topology([edge("A", "B")]).max_window_s(["Z"]) == 0
    assert Topology().max_window_s(["A"]) == 0
    assert Topology([edge("A", "B")]).max_window_s([]) == 0


def test_the_window_counts_incoming_edges_too(edge) -> None:
    # an event on C can still be followed by one on... nothing; but one on A could precede it,
    # so a group on C must wait for edges that END at C as well
    assert Topology([edge("A", "C", max_s=60)]).max_window_s(["C"]) == 60


def test_edges_are_kept_as_given(edge) -> None:
    edges = [edge("A", "B"), edge("B", "C")]
    assert Topology(edges).edges == edges
