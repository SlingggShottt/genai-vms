"""Linking two events: temporal fit, the camera graph's directions, and the score."""

from __future__ import annotations

import pytest
from correlation.domain.config import CorrelationConfig
from correlation.domain.scoring import best_link, overlap_fit, transit_fit
from correlation.domain.topology import Topology

CFG = CorrelationConfig(compatibility={"intrusion": {"intrusion": 1.0, "running": 0.5}})


# --- transit_fit ---------------------------------------------------------------------------


def test_transit_fit_is_one_at_the_centre_and_zero_at_the_bounds() -> None:
    assert transit_fit(47.5, 5, 90) == pytest.approx(1.0)
    assert transit_fit(5, 5, 90) == pytest.approx(0.0)
    assert transit_fit(90, 5, 90) == pytest.approx(0.0)


def test_transit_fit_falls_off_linearly() -> None:
    assert transit_fit(26.25, 5, 90) == pytest.approx(0.5)
    assert transit_fit(68.75, 5, 90) == pytest.approx(0.5)  # symmetric about the centre
    assert transit_fit(23, 5, 90) == pytest.approx(1 - 24.5 / 42.5)


def test_transit_fit_is_none_outside_the_window() -> None:
    assert transit_fit(4.99, 5, 90) is None
    assert transit_fit(90.01, 5, 90) is None
    assert transit_fit(-3, 5, 90) is None


def test_a_zero_width_window_fits_only_exactly() -> None:
    assert transit_fit(10, 10, 10) == 1.0
    assert transit_fit(10.5, 10, 10) is None


# --- overlap_fit ---------------------------------------------------------------------------


def test_intersecting_windows_fit_perfectly(ev) -> None:
    assert overlap_fit(ev("a", start=0, end=10), ev("b", start=5, end=15), 3) == (1.0, 0.0)
    assert overlap_fit(ev("a", start=0, end=10), ev("b", start=10, end=20), 3) == (
        1.0,
        0.0,
    )  # touching
    assert overlap_fit(ev("a", start=0, end=10), ev("b", start=2, end=4), 3) == (1.0, 0.0)  # inside


def test_each_window_is_widened_by_the_tolerance_so_the_gap_may_be_twice_it(ev) -> None:
    a = ev("a", start=0, end=10)
    assert overlap_fit(a, ev("b", start=13, end=20), 3) == pytest.approx((0.5, 3.0))
    assert overlap_fit(a, ev("b", start=16, end=20), 3) == pytest.approx((0.0, 6.0))  # at 2*tau
    assert overlap_fit(a, ev("b", start=16.01, end=20), 3) is None
    # symmetric in the two events
    assert overlap_fit(ev("b", start=13, end=20), a, 3) == pytest.approx((0.5, 3.0))


def test_zero_tolerance_means_the_windows_must_touch(ev) -> None:
    assert overlap_fit(ev("a", end=10), ev("b", start=10, end=20), 0) == (1.0, 0.0)
    assert overlap_fit(ev("a", end=10), ev("b", start=10.5, end=20), 0) is None


# --- best_link: the camera graph ------------------------------------------------------------


def test_a_transit_edge_links_an_event_after_the_earlier_cameras_one(ev, edge) -> None:
    topo = Topology([edge("A", "B", min_s=5, max_s=90)])
    first, later = ev("A", start=0, end=10), ev("B", start=33, end=40)  # delta = 23 s
    link = best_link(later, first, topo, CFG)  # `later` is the new event
    assert link is not None
    assert (link.from_event, link.to_event) == (first.event_id, later.event_id)
    assert (link.edge_type, link.delta_s) == ("transit", 23.0)
    assert link.score == pytest.approx(0.7 * (1 - 24.5 / 42.5) + 0.3 * 1.0)


def test_the_new_event_may_be_the_earlier_one(ev, edge) -> None:
    topo = Topology([edge("A", "B")])
    existing_later, new_earlier = ev("B", start=33, end=40), ev("A", start=0, end=10)
    link = best_link(new_earlier, existing_later, topo, CFG)
    assert link is not None and link.from_event == new_earlier.event_id


def test_a_one_way_transit_edge_does_not_link_against_its_direction(ev, edge) -> None:
    topo = Topology([edge("A", "B")])  # A -> B only
    on_b_first, on_a_later = ev("B", start=0, end=10), ev("A", start=33, end=40)
    assert best_link(on_a_later, on_b_first, topo, CFG) is None


def test_a_bidirectional_transit_edge_links_both_ways(ev, edge) -> None:
    topo = Topology([edge("A", "B", bidirectional=True)])
    on_b_first, on_a_later = ev("B", start=0, end=10), ev("A", start=33, end=40)
    link = best_link(on_a_later, on_b_first, topo, CFG)
    assert link is not None and link.from_event == on_b_first.event_id


@pytest.mark.parametrize("later_start", [14.99, 100.01])
def test_a_transit_delta_outside_the_window_does_not_link(ev, edge, later_start) -> None:
    topo = Topology([edge("A", "B", min_s=5, max_s=90)])
    assert (
        best_link(ev("B", start=later_start + 10, end=later_start + 20), ev("A", end=10), topo, CFG)
        is None
    )


def test_transit_needs_the_later_event_to_start_after_the_earlier_one_ended(ev, edge) -> None:
    topo = Topology([edge("A", "B", min_s=0, max_s=30)])
    overlapping = best_link(ev("B", start=5, end=15), ev("A", start=0, end=10), topo, CFG)
    assert overlapping is None  # delta = -5: B began before A ended


def test_an_overlap_edge_links_events_whose_windows_meet(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap", tolerance_s=3)])
    link = best_link(ev("B", start=5, end=15), ev("A", start=0, end=10), topo, CFG)
    assert link is not None and (link.edge_type, link.delta_s) == ("overlap", 0.0)
    assert link.score == pytest.approx(1.0)  # fit 1, compat 1


def test_an_overlap_edge_is_symmetric(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    a, b = ev("A", start=0, end=10), ev("B", start=12, end=20)
    assert best_link(a, b, topo, CFG) is not None
    assert best_link(b, a, topo, CFG) is not None


def test_no_edge_between_the_cameras_means_no_link(ev, edge) -> None:
    topo = Topology([edge("A", "C")])
    assert best_link(ev("B", start=0, end=10), ev("A", start=0, end=10), topo, CFG) is None
    assert best_link(ev("B"), ev("A"), Topology(), CFG) is None


def test_events_on_the_same_camera_never_link(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    assert best_link(ev("A", start=0, end=10), ev("A", start=0, end=10), topo, CFG) is None


# --- best_link: type compatibility and the threshold ----------------------------------------


def test_incompatible_event_types_never_link(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    assert best_link(ev("A", "crowding"), ev("B", "intrusion"), topo, CFG) is None  # unlisted pair


def test_a_pair_listed_with_weight_zero_is_incompatible_too(ev, edge) -> None:
    cfg = CorrelationConfig(compatibility={"intrusion": {"running": 0.0}})
    topo = Topology([edge("A", "B", "overlap")])
    assert best_link(ev("A", "intrusion"), ev("B", "running"), topo, cfg) is None


def test_compatibility_is_symmetric(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    one = best_link(ev("A", "intrusion"), ev("B", "running"), topo, CFG)
    other = best_link(ev("B", "running"), ev("A", "intrusion"), topo, CFG)
    assert one is not None and other is not None
    assert one.score == pytest.approx(other.score) == pytest.approx(0.7 + 0.3 * 0.5)


def test_the_score_must_reach_the_threshold(ev, edge) -> None:
    topo = Topology([edge("A", "B", min_s=0, max_s=100)])
    # delta 2 s: fit = 1 - 48/50 = 0.04; compat 0.5 -> 0.7*0.04 + 0.3*0.5 = 0.178 < 0.5
    assert (
        best_link(ev("B", "running", start=12, end=20), ev("A", "intrusion", end=10), topo, CFG)
        is None
    )
    # the same timing against a threshold of 0.1 does link
    loose = CorrelationConfig(link_threshold=0.1, compatibility={"intrusion": {"running": 0.5}})
    assert best_link(
        ev("B", "running", start=12, end=20), ev("A", "intrusion", end=10), topo, loose
    )


def test_the_threshold_is_inclusive(ev, edge) -> None:
    # fit 1 (overlapping windows) * 0.7 + compat 0.5 * 0.3 = 0.85; make the threshold exactly that
    cfg = CorrelationConfig(link_threshold=0.85, compatibility={"intrusion": {"running": 0.5}})
    topo = Topology([edge("A", "B", "overlap")])
    assert best_link(ev("A", "intrusion"), ev("B", "running"), topo, cfg) is not None
    stricter = cfg.model_copy(update={"link_threshold": 0.8501})
    assert best_link(ev("A", "intrusion"), ev("B", "running"), topo, stricter) is None


def test_the_best_of_several_valid_edges_wins_whichever_is_listed_first(ev, edge) -> None:
    # B starts 2 s after A ends, and two edges join the cameras; BOTH clear the threshold:
    #   transit [0, 4] s: delta 2 is the exact centre            -> fit 1.0 -> score 1.00
    #   overlap tau 5:    a gap of 2 s of 2*tau = 10            -> fit 0.8 -> score 0.86
    transit, overlap = edge("A", "B", min_s=0, max_s=4), edge("A", "B", "overlap", tolerance_s=5)
    a, b = ev("A", start=0, end=10), ev("B", start=12, end=20)
    for edges in ([transit, overlap], [overlap, transit]):
        link = best_link(b, a, Topology(edges), CFG)
        assert link is not None and link.edge_type == "transit"
        assert link.score == pytest.approx(1.0)
    assert best_link(b, a, Topology([overlap]), CFG).score == pytest.approx(0.7 * 0.8 + 0.3)  # type: ignore[union-attr]

    # and the other way round: when the overlap edge is the better fit it wins
    wide = edge("A", "B", min_s=0, max_s=100)  # delta 2 of a 100 s window: fit 0.04 -> below 0.5
    assert best_link(b, a, Topology([wide, overlap]), CFG).edge_type == "overlap"  # type: ignore[union-attr]


def test_an_overlap_link_runs_from_the_event_already_in_the_group_to_the_new_one(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    existing, new = ev("A", start=0, end=10), ev("B", start=5, end=15)
    link = best_link(new, existing, topo, CFG)
    assert link is not None
    assert (link.from_event, link.to_event) == (existing.event_id, new.event_id)


# --- the contract fixtures' numbers ----------------------------------------------------------


def test_the_fixture_scenario_scores_match_the_published_correlation_fixture(
    fixture_events, fixture_topology, shipped_config
) -> None:
    intrusion, running = fixture_events["intrusion"], fixture_events["running"]
    abandoned = fixture_events["abandoned_object"]
    first = best_link(running, intrusion, fixture_topology, shipped_config)
    second = best_link(running, abandoned, fixture_topology, shipped_config)
    assert first is not None and second is not None
    assert (first.from_event, first.to_event, first.delta_s) == (
        intrusion.event_id,
        running.event_id,
        23.0,
    )
    assert (second.from_event, second.to_event, second.delta_s) == (
        abandoned.event_id,
        running.event_id,
        53.0,
    )
    assert round(first.score, 4) == 0.5365
    assert round(second.score, 4) == 0.6973
    # and the intrusion and the abandoned object do NOT link directly: 8 s apart, tolerance 3 s
    assert best_link(intrusion, abandoned, fixture_topology, shipped_config) is None
