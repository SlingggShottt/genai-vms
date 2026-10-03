"""The correlation engine: grouping, merging, the close rule, publishing (design §7.5)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from correlation.domain.config import CorrelationConfig
from correlation.domain.engine import (
    add_event,
    close_due,
    due_for_publish,
    mark_published,
    to_message,
)
from correlation.domain.topology import Topology
from correlation.domain.types import Group
from vms_common.contracts.correlation import CorrelationV1

T0 = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)  # the fixtures' scenario starts at 10:15:00Z


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


CFG = CorrelationConfig(
    compatibility={
        "intrusion": {"intrusion": 1.0, "running": 0.8},
        "running": {"running": 1.0},
    },
    grace_s=30,
    publish_throttle_s=5,
)


def place(groups: list[Group], event, topo: Topology, cfg: CorrelationConfig = CFG, now: float = 0):
    """add_event, then keep `groups` as the engine's caller would: new groups appended."""
    outcome = add_event(groups, event, topology=topo, config=cfg, now=at(now))
    for g in outcome.changed:
        if g not in groups:
            groups.append(g)
    return outcome


# --- adding events ----------------------------------------------------------------------------


def test_the_first_event_starts_a_single_event_group(ev) -> None:
    groups: list[Group] = []
    event = ev("A")
    outcome = place(groups, event, Topology())
    (group,) = outcome.changed
    assert (group.status, group.revision, group.members, group.links) == ("open", 1, [event], [])
    assert group.publish_pending and group.last_published_at is None
    assert outcome.group_id == group.id and not outcome.duplicate and outcome.new_links == []
    uuid.UUID(group.id)  # a real uuid


def test_an_unlinked_event_starts_its_own_group(ev, edge) -> None:
    topo = Topology([edge("A", "B")])
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), topo)
    place(groups, ev("B", start=500, end=510), topo)  # far outside the 5..90 s window
    assert len(groups) == 2 and all(len(g.members) == 1 for g in groups)


def test_a_linked_event_joins_the_group_and_records_the_link(ev, edge) -> None:
    topo = Topology([edge("A", "B")])
    groups: list[Group] = []
    first, second = ev("A", start=0, end=10), ev("B", start=33, end=40)
    place(groups, first, topo)
    outcome = place(groups, second, topo)
    (group,) = groups
    assert [m.event_id for m in group.members] == [first.event_id, second.event_id]
    assert outcome.changed == [group] and outcome.group_id == group.id
    (link,) = group.links
    assert (link.from_event, link.to_event, link.delta_s) == (first.event_id, second.event_id, 23.0)
    assert outcome.new_links == [link]
    assert group.revision == 2 and group.publish_pending


def test_an_event_links_to_each_member_it_fits_and_every_link_is_kept(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap"), edge("A", "C", "overlap")])
    groups: list[Group] = []
    place(groups, ev("B", start=0, end=10), topo)
    place(groups, ev("C", start=0, end=10), topo)  # B-C: no edge, so a separate group
    assert len(groups) == 2
    # an event on A overlaps both: it bridges the two groups
    outcome = place(groups, ev("A", start=0, end=10), topo)
    assert len(outcome.new_links) == 2


def test_incompatible_event_types_do_not_group_even_when_timing_and_graph_fit(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    groups: list[Group] = []
    place(groups, ev("A", "intrusion"), topo)
    place(groups, ev("B", "crowding"), topo)  # crowding is not in CFG's matrix
    assert len(groups) == 2


def test_the_same_event_delivered_twice_is_a_noop(ev, edge) -> None:
    topo = Topology([edge("A", "B")])
    groups: list[Group] = []
    first = ev("A", start=0, end=10)
    place(groups, first, topo)
    snapshot = (groups[0].revision, list(groups[0].members))
    repeat = place(groups, first, topo)
    assert repeat.duplicate and repeat.changed == [] and repeat.group_id == groups[0].id
    assert (groups[0].revision, groups[0].members) == snapshot


def test_groups_of_other_sites_are_ignored(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    groups: list[Group] = []
    place(groups, ev("A", site="north"), topo)
    place(groups, ev("B", site="south"), topo)
    assert len(groups) == 2


def test_closed_and_merged_groups_are_never_joined(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), topo)
    groups[0].status = "closed"
    place(groups, ev("B", start=0, end=10), topo)
    assert len(groups) == 2 and groups[0].status == "closed" and len(groups[0].members) == 1


def test_every_group_gets_its_own_uuid(ev) -> None:
    groups: list[Group] = []
    for camera in "ABCDE":
        place(groups, ev(camera), Topology())
    assert len({g.id for g in groups}) == 5
    for g in groups:
        uuid.UUID(g.id)


# --- merging ----------------------------------------------------------------------------------


def _two_groups_and_a_bridge(ev, edge):
    topo = Topology([edge("A", "C"), edge("B", "C")])  # A->C and B->C
    groups: list[Group] = []
    on_a, on_b = ev("A", "intrusion", 0, 10), ev("B", "intrusion", 0, 10)
    place(groups, on_a, topo, now=1)
    place(groups, on_b, topo, now=2)  # no A-B edge: two groups, A's the older
    assert len(groups) == 2
    bridge = ev("C", "running", 33, 40)
    return topo, groups, on_a, on_b, bridge


def test_an_event_linking_two_groups_merges_them_into_the_older(ev, edge) -> None:
    topo, groups, on_a, on_b, bridge = _two_groups_and_a_bridge(ev, edge)
    older, younger = groups
    outcome = place(groups, bridge, topo, now=40)

    assert outcome.changed == [older, younger]  # survivor first, then the absorbed group
    assert outcome.group_id == older.id
    assert older.status == "open" and older.revision == 2
    assert [m.event_id for m in older.members] == [on_a.event_id, on_b.event_id, bridge.event_id]
    assert len(older.links) == 2 and older.publish_pending
    assert (younger.status, younger.merged_into, younger.closed_at) == ("merged", older.id, at(40))
    assert younger.links == [] and younger.revision == 2 and younger.publish_pending


def test_the_survivor_is_the_oldest_group_even_when_ids_do_not_say_so(ev, edge) -> None:
    topo = Topology([edge("A", "C"), edge("B", "C")])
    groups: list[Group] = []
    place(groups, ev("A", "intrusion", 0, 10), topo, now=1)
    place(groups, ev("B", "intrusion", 0, 10), topo, now=2)
    older, younger = groups
    # UUIDv7 ids are only ordered across milliseconds: make them disagree with creation order
    older.id, younger.id = (
        "ffffffff-ffff-7fff-8fff-ffffffffffff",
        "00000000-0000-7000-8000-000000000000",
    )
    outcome = place(groups, ev("C", "running", 33, 40), topo, now=40)
    assert outcome.group_id == older.id  # created first, so it survives, whatever the ids say
    assert (younger.status, younger.merged_into) == ("merged", older.id)


def test_groups_created_at_the_same_instant_merge_deterministically_by_id(ev, edge) -> None:
    topo = Topology([edge("A", "C"), edge("B", "C")])
    groups: list[Group] = []
    place(groups, ev("A", "intrusion", 0, 10), topo, now=5)
    place(groups, ev("B", "intrusion", 0, 10), topo, now=5)
    survivor_id = min(g.id for g in groups)
    outcome = place(groups, ev("C", "running", 33, 40), topo, now=40)
    assert outcome.group_id == survivor_id


def test_an_absorbed_groups_own_links_move_to_the_survivor(ev, edge) -> None:
    topo = Topology([edge("A", "B"), edge("C", "D"), edge("B", "E"), edge("D", "E")])
    groups: list[Group] = []
    a, b = ev("A", start=0, end=10), ev("B", start=33, end=40)
    c, d = ev("C", start=0, end=10), ev("D", start=33, end=40)
    for e in (a, b, c, d):
        place(groups, e, topo)
    assert len(groups) == 2 and all(len(g.links) == 1 for g in groups)
    place(groups, ev("E", start=80, end=90), topo)  # links to b (B->E) and d (D->E)
    survivor = next(g for g in groups if g.status == "open")
    assert len(survivor.members) == 5 and len(survivor.links) == 4  # 1 + 1 + 2 new
    (absorbed,) = [g for g in groups if g.status == "merged"]
    assert absorbed.links == []  # its link now lives on the survivor, once


def test_the_group_cap_stops_a_link_from_growing_a_group_past_it(ev, edge) -> None:
    cfg = CFG.model_copy(update={"max_group_events": 2})
    topo = Topology([edge("A", "B"), edge("B", "C")])
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), topo, cfg)
    place(groups, ev("B", start=33, end=40), topo, cfg)  # joins: group of 2 (the cap)
    assert len(groups) == 1 and len(groups[0].members) == 2
    outcome = place(groups, ev("C", start=80, end=90), topo, cfg)  # would link to B, but full
    assert len(groups) == 2 and len(groups[1].members) == 1 and outcome.new_links == []


def test_a_merge_that_would_exceed_the_cap_joins_only_what_fits(ev, edge) -> None:
    cfg = CFG.model_copy(update={"max_group_events": 3})
    topo, groups, on_a, on_b, bridge = _two_groups_and_a_bridge(ev, edge)
    # 1 (the bridge) + 1 + 1 = 3: both fit
    place(groups, bridge, topo, cfg)
    assert sum(1 for g in groups if g.status == "open") == 1

    topo2, groups2, _, _, bridge2 = _two_groups_and_a_bridge(ev, edge)
    tight = CFG.model_copy(update={"max_group_events": 2})  # only one group fits beside the bridge
    place(groups2, bridge2, topo2, tight)
    assert sorted(g.status for g in groups2) == ["open", "open"]  # nobody merged
    assert sorted(len(g.members) for g in groups2) == [1, 2]
    assert len(groups2[0].members) == 2 and len(groups2[1].members) == 1  # the older took the slot


# --- severity and derived fields -------------------------------------------------------------


def test_group_summary_fields_follow_its_members(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap"), edge("A", "C", "overlap")])
    groups: list[Group] = []
    place(groups, ev("A", "intrusion", 10, 20, severity="medium"), topo)
    place(groups, ev("B", "intrusion", 15, 30, severity="critical"), topo)
    place(groups, ev("C", "running", 0, 12, severity="low"), topo)
    (group,) = groups
    assert group.max_severity == "critical"
    assert group.camera_ids == ["A", "B", "C"]
    assert group.event_types == ["intrusion", "running"]
    assert (group.start_ts, group.end_ts) == (at(0), at(30))


# --- closing ----------------------------------------------------------------------------------


def test_a_group_closes_after_the_longest_transit_window_plus_grace(ev, edge) -> None:
    topo = Topology([edge("A", "B", max_s=90)])
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), topo)
    wait = 90 + 30  # max transit + grace
    assert close_due(groups, topology=topo, config=CFG, now=at(10 + wait)) == []  # not > wait
    (closed,) = close_due(groups, topology=topo, config=CFG, now=at(10 + wait + 0.001))
    assert (closed.status, closed.closed_at, closed.revision) == (
        "closed",
        at(10 + wait + 0.001),
        2,
    )
    assert closed.publish_pending


def test_a_camera_with_no_edges_closes_after_just_the_grace_period(ev) -> None:
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), Topology())
    assert close_due(groups, topology=Topology(), config=CFG, now=at(40)) == []
    assert len(close_due(groups, topology=Topology(), config=CFG, now=at(40.5))) == 1


def test_the_close_window_uses_every_camera_of_the_group(ev, edge) -> None:
    topo = Topology([edge("A", "B", max_s=20), edge("B", "C", max_s=200)])
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), topo)
    place(groups, ev("B", start=20, end=30), topo)  # joins; the group now spans A and B
    (group,) = groups
    # B touches the 200 s edge, so the group waits 200 + 30 after its last event (ended at 30)
    assert close_due(groups, topology=topo, config=CFG, now=at(30 + 229)) == []
    assert close_due(groups, topology=topo, config=CFG, now=at(30 + 231)) == [group]


def test_an_overlap_edge_keeps_a_group_open_for_twice_its_tolerance(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap", tolerance_s=40)])
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), topo)
    assert close_due(groups, topology=topo, config=CFG, now=at(10 + 80 + 30)) == []
    assert len(close_due(groups, topology=topo, config=CFG, now=at(10 + 80 + 31))) == 1


def test_only_open_groups_close_and_only_once(ev) -> None:
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), Topology())
    assert len(close_due(groups, topology=Topology(), config=CFG, now=at(1000))) == 1
    assert close_due(groups, topology=Topology(), config=CFG, now=at(2000)) == []
    groups[0].status = "merged"
    assert close_due(groups, topology=Topology(), config=CFG, now=at(3000)) == []


def test_an_event_dated_in_the_future_does_not_close_its_group(ev) -> None:
    groups: list[Group] = []
    place(groups, ev("A", start=500, end=510), Topology())  # clock skew
    assert close_due(groups, topology=Topology(), config=CFG, now=at(0)) == []


def test_a_late_event_can_still_join_a_group_that_is_open(ev, edge) -> None:
    topo = Topology([edge("A", "B", max_s=90)])
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), topo)
    assert close_due(groups, topology=topo, config=CFG, now=at(100)) == []
    outcome = place(groups, ev("B", start=60, end=70), topo, now=100)
    assert len(groups) == 1 and len(outcome.new_links) == 1


# --- publishing -------------------------------------------------------------------------------


def test_a_new_group_is_announced_at_once(ev) -> None:
    groups: list[Group] = []
    place(groups, ev("A"), Topology())
    assert due_for_publish(groups, config=CFG, now=at(0)) == groups


def test_an_open_group_is_republished_at_most_every_throttle_period(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    groups: list[Group] = []
    place(groups, ev("A"), topo)
    (group,) = groups
    mark_published(group, revision=group.revision, now=at(0))
    assert due_for_publish(groups, config=CFG, now=at(1)) == []  # nothing changed
    place(groups, ev("B"), topo, now=1)  # a change...
    assert due_for_publish(groups, config=CFG, now=at(4.99)) == []  # ...held back
    assert due_for_publish(groups, config=CFG, now=at(5)) == [group]  # ...due at the throttle
    assert due_for_publish(groups, config=CFG, now=at(60)) == [group]


def test_closing_and_merging_publish_without_waiting_for_the_throttle(ev) -> None:
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), Topology())
    (group,) = groups
    mark_published(group, revision=1, now=at(1))
    close_due(groups, topology=Topology(), config=CFG, now=at(1000))
    assert due_for_publish(groups, config=CFG, now=at(1000)) == [
        group
    ]  # 1 s after the last send? no: long after
    mark_published(group, revision=group.revision, now=at(1000))
    group.status, group.publish_pending = "merged", True
    assert due_for_publish(groups, config=CFG, now=at(1000.01)) == [group]  # final: no throttle


def test_a_final_state_is_never_held_back_even_right_after_a_publish(ev) -> None:
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), Topology())
    (group,) = groups
    mark_published(group, revision=1, now=at(100))
    close_due(groups, topology=Topology(), config=CFG, now=at(100.5) + timedelta(days=1))
    assert due_for_publish(groups, config=CFG, now=at(100.6)) == [group]


def test_a_change_during_a_publish_keeps_the_group_pending(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap")])
    groups: list[Group] = []
    place(groups, ev("A"), topo)
    (group,) = groups
    sent_revision = group.revision
    place(groups, ev("B"), topo, now=1)  # the group changed while revision 1 was in flight
    mark_published(group, revision=sent_revision, now=at(2))
    assert group.publish_pending and group.last_published_at == at(2)
    mark_published(group, revision=group.revision, now=at(8))
    assert not group.publish_pending


# --- messages ---------------------------------------------------------------------------------


def test_replaying_the_fixture_events_reproduces_the_published_correlation_message(
    fixture_events, fixture_topology, shipped_config, fixtures_dir
) -> None:
    """The scenario of `fixtures/correlation_v1.json`: an abandoned bag (cam03) and an intrusion
    (cam02) start as separate groups; a running event on cam04 bridges them; the merged group
    closes. The engine must reproduce the fixture message and the merged-group message."""
    cfg = shipped_config
    groups: list[Group] = []
    sequence = [  # (event, wall-clock arrival in seconds from the fixture's 10:15:00 origin)
        (fixture_events["abandoned_object"], 14),
        (fixture_events["intrusion"], 48),
        (fixture_events["running"], 74),
    ]
    outcomes = []
    for event, arrival in sequence:
        outcomes.append(
            add_event(groups, event, topology=fixture_topology, config=cfg, now=at(arrival))
        )
        groups.extend(g for g in outcomes[-1].changed if g not in groups)
    assert [len(o.changed) for o in outcomes] == [1, 1, 2]  # the third event merged two groups
    survivor, absorbed = outcomes[2].changed

    # while the last event ended at 10:16:11 the group stays open for 120 s + 30 s grace
    assert close_due(groups, topology=fixture_topology, config=cfg, now=at(11 + 60 + 150)) == []
    close_due(groups, topology=fixture_topology, config=cfg, now=at(11 + 60 + 150 + 1))

    closed = json.loads((fixtures_dir / "correlation_v1.json").read_text())
    merged = json.loads((fixtures_dir / "correlation_v1_merged.json").read_text())
    message = to_message(survivor)
    assert CorrelationV1.model_validate(json.loads(message.model_dump_json())).status == "closed"
    mine = message.model_dump(mode="json")
    # the contract fixture predates exact timestamps; compare everything that is not a timestamp
    for key in ("event_ids", "camera_ids", "event_types", "max_severity", "links", "status"):
        assert mine[key] == closed[key], key
    assert survivor.revision == closed["revision"] == 3
    assert absorbed.revision == merged["revision"] == 2

    absorbed_msg = to_message(absorbed).model_dump(mode="json")
    for key in (
        "event_ids",
        "camera_ids",
        "event_types",
        "status",
        "links",
        "max_severity",
        "revision",
    ):
        assert absorbed_msg[key] == merged[key], key
    assert absorbed_msg["merged_into"] == survivor.id


def test_the_messages_links_come_in_a_canonical_order_whatever_the_groups_order(ev, edge) -> None:
    topo = Topology([edge("A", "B", "overlap"), edge("A", "C", "overlap")])
    groups: list[Group] = []
    for camera in "BCA":
        place(groups, ev(camera), topo)  # A bridges the groups of B and C
    group = next(g for g in groups if g.status == "open")
    assert len(group.links) == 2
    shuffled = list(reversed(group.links))
    expected = [
        (link.from_event, link.to_event)
        for link in sorted(group.links, key=lambda x: (x.from_event, x.to_event))
    ]
    group.links = shuffled
    assert [(link.from_event, link.to_event) for link in to_message(group).links] == expected


def test_the_message_rounds_scores_and_carries_the_groups_state(ev, edge) -> None:
    topo = Topology([edge("A", "B")])
    groups: list[Group] = []
    place(groups, ev("A", start=0, end=10), topo)
    place(groups, ev("B", start=33, end=40), topo)
    message = to_message(groups[0])
    assert message.status == "open" and message.revision == 2
    assert message.links[0].score == round(message.links[0].score, 4)
    assert message.links[0].delta_s == 23.0
    assert message.group_id == groups[0].id and message.event_ids == groups[0].event_ids
