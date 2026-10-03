"""The correlation consumer and sweeper end to end against real Postgres (P3-J2): events in,
groups persisted, `correlation.v1` messages out (to a recording publisher)."""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import timedelta

import pytest
from correlation.adapters import group_repository as repo
from prometheus_client import REGISTRY
from sqlalchemy import text
from vms_common.contracts.correlation import CorrelationV1
from vms_db.session import session_scope

pytestmark = pytest.mark.integration

SCENARIO = ("abandoned_object", "intrusion", "running_skipped")  # arrival order of the fixtures
ARRIVALS = {"abandoned_object": 14, "intrusion": 48, "running_skipped": 74}


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def groups(rig, status: str | None = None):
    async with session_scope(rig.session_factory) as session:
        rows = (
            await session.execute(
                text("SELECT id::text FROM events.correlation_groups ORDER BY created_at, id")
            )
        ).scalars()
        found = [await repo.get_group(session, gid) for gid in rows]
    return [g for g in found if g and (status is None or g.status == status)]


async def deliver_scenario(rig, event, order=SCENARIO) -> None:
    for name in order:
        rig.clock.set(ARRIVALS[name])
        await rig.deliver(event(name))


# --- grouping ---------------------------------------------------------------------------------


async def test_a_single_event_becomes_one_pending_open_group(rig, event) -> None:
    rig.clock.set(5)
    await rig.deliver(event("intrusion"))
    (group,) = await groups(rig)
    assert (group.status, group.revision, group.publish_pending) == ("open", 1, True)
    assert group.event_ids == ["0192f3d1-0001-7000-8000-000000000001"]
    assert group.camera_ids == ["cam02"] and group.max_severity == "high" and group.links == []


async def test_the_fixture_scenario_ends_as_the_published_fixtures_describe(
    rig, event, fixtures_dir
) -> None:
    await deliver_scenario(rig, event)

    open_groups, merged = await groups(rig, "open"), await groups(rig, "merged")
    (survivor,), (absorbed,) = open_groups, merged
    assert absorbed.merged_into == survivor.id and absorbed.links == []
    assert survivor.event_ids == [  # the oldest group (the bag) absorbed the intrusion's
        "0192f3d1-0003-7000-8000-000000000003",
        "0192f3d1-0001-7000-8000-000000000001",
        "0192f3d1-0002-7000-8000-000000000002",
    ]
    assert survivor.camera_ids == ["cam02", "cam03", "cam04"]
    assert sorted((link.delta_s, round(link.score, 4)) for link in survivor.links) == [
        (23.0, 0.5365),
        (53.0, 0.6973),
    ]

    # first sweep: both changes are announced at once (a first announcement and a final one)
    rig.clock.set(75)
    await rig.sweeper.sweep()
    sent = {m.group_id: m for m in rig.publisher.messages}
    assert sent[survivor.id].status == "open" and sent[survivor.id].revision == 2
    assert sent[absorbed.id].status == "merged" and sent[absorbed.id].merged_into == survivor.id

    # nothing more until the group can close: last event ended 10:16:11; window 120 s + grace 30 s
    rig.clock.set(11 + 60 + 150)
    await rig.sweeper.sweep()
    assert len(rig.publisher.messages) == 2
    rig.clock.set(11 + 60 + 151)
    await rig.sweeper.sweep()
    closed = rig.publisher.messages[-1]
    assert (closed.status, closed.revision, closed.group_id) == ("closed", 3, survivor.id)

    fixture = json.loads((fixtures_dir / "correlation_v1.json").read_text())
    published = closed.model_dump(mode="json")
    for key in (
        "event_ids",
        "camera_ids",
        "event_types",
        "max_severity",
        "links",
        "status",
        "revision",
    ):
        assert published[key] == fixture[key], key
    CorrelationV1.model_validate(published)


@pytest.mark.parametrize("order", list(itertools.permutations(SCENARIO)))
async def test_every_arrival_order_ends_in_one_group_holding_all_three(rig, event, order) -> None:
    await deliver_scenario(rig, event, order)
    (group,) = await groups(rig, "open")
    assert sorted(group.event_ids) == [
        "0192f3d1-0001-7000-8000-000000000001",
        "0192f3d1-0002-7000-8000-000000000002",
        "0192f3d1-0003-7000-8000-000000000003",
    ]
    assert len(group.links) == 2
    assert {g.status for g in await groups(rig)} <= {"open", "merged"}


async def test_a_verification_skipped_event_groups_like_a_verified_one(rig, event) -> None:
    await rig.deliver(event("intrusion"))
    await rig.deliver(event("running_skipped"))  # verification.status == "skipped"
    (group,) = await groups(rig, "open")
    assert len(group.members) == 2 and len(group.links) == 1


async def test_events_of_different_sites_never_group(rig, event) -> None:
    await rig.deliver(event("intrusion", site_id="north"))
    await rig.deliver(event("running_skipped", site_id="south"))
    assert len(await groups(rig, "open")) == 2


async def test_an_event_nothing_links_to_is_a_group_of_one(rig, event) -> None:
    far_later = event(
        "running_skipped", start_ts="2026-10-05T11:00:00Z", end_ts="2026-10-05T11:00:05Z"
    )
    await rig.deliver(event("intrusion"))
    await rig.deliver(far_later)
    assert [len(g.members) for g in await groups(rig, "open")] == [1, 1]


# --- idempotency and restart ------------------------------------------------------------------


async def test_a_redelivered_event_changes_nothing(rig, event) -> None:
    before = sample("vms_correlation_events_total", result="duplicate")
    rig.clock.set(5)
    await rig.deliver(event("intrusion"))
    (first,) = await groups(rig)
    await rig.deliver(event("intrusion"))
    await rig.deliver(event("intrusion"))
    (after,) = await groups(rig)
    assert (after.revision, after.event_ids, after.links) == (
        first.revision,
        first.event_ids,
        first.links,
    )
    assert sample("vms_correlation_events_total", result="duplicate") == before + 2


async def test_a_redelivered_event_is_ignored_even_after_its_group_closed(rig, event) -> None:
    await rig.deliver(event("intrusion"))
    rig.clock.set(10_000)
    await rig.sweeper.sweep()  # closes the group
    assert [g.status for g in await groups(rig)] == ["closed"]
    await rig.deliver(event("intrusion"))  # Kafka redelivers it much later
    assert [g.status for g in await groups(rig)] == ["closed"]  # no second group


async def test_a_restart_carries_on_from_the_database(rig, event) -> None:
    rig.clock.set(14)
    await rig.deliver(event("abandoned_object"))
    rig.clock.set(48)
    await rig.deliver(event("intrusion"))
    restarted = rig.rebuild()  # new consumer, sweeper and (empty) in-memory state
    restarted.clock.set(74)
    await restarted.deliver(event("running_skipped"))  # must still bridge the two stored groups
    (survivor,) = await groups(restarted, "open")
    assert len(survivor.members) == 3 and len(await groups(restarted, "merged")) == 1


async def test_a_restart_closes_what_was_due_while_it_was_down(rig, event) -> None:
    await rig.deliver(event("intrusion"))
    restarted = rig.rebuild()
    restarted.clock.set(5000)
    await restarted.sweeper.sweep()
    assert [g.status for g in await groups(restarted)] == ["closed"]


# --- publishing --------------------------------------------------------------------------------


async def test_nothing_is_announced_before_the_first_sweep_and_a_swept_group_is_not_resent(
    rig, event
) -> None:
    await rig.deliver(event("intrusion"))
    assert rig.publisher.messages == []
    rig.clock.set(1)
    await rig.sweeper.sweep()
    await rig.sweeper.sweep()
    assert [m.status for m in rig.publisher.messages] == ["open"]  # announced once, not again


async def test_a_growing_open_group_is_republished_at_most_every_five_seconds(rig, event) -> None:
    rig.clock.set(0)
    await rig.deliver(event("intrusion"))
    await rig.sweeper.sweep()
    assert [m.revision for m in rig.publisher.messages] == [1]

    rig.clock.set(2)
    await rig.deliver(event("running_skipped"))  # the group changes (revision 2)
    rig.clock.set(4.9)
    await rig.sweeper.sweep()
    assert [m.revision for m in rig.publisher.messages] == [1]  # held back by the throttle
    rig.clock.set(5)
    await rig.sweeper.sweep()
    assert [m.revision for m in rig.publisher.messages] == [1, 2]


async def test_a_kafka_outage_loses_nothing_the_change_is_sent_once_it_is_back(rig, event) -> None:
    await rig.deliver(event("intrusion"))
    rig.publisher.fail_next = 1
    with pytest.raises(ConnectionError):
        await rig.sweeper.sweep()
    (group,) = await groups(rig)
    assert group.publish_pending and rig.publisher.messages == []  # stored, not yet announced

    await rig.sweeper.sweep()  # the next tick
    assert [m.group_id for m in rig.publisher.messages] == [group.id]
    (group,) = await groups(rig)
    assert not group.publish_pending


async def test_a_crash_between_sending_and_recording_resends_rather_than_loses(rig, event) -> None:
    await rig.deliver(event("intrusion"))
    await rig.sweeper.sweep()
    # simulate: the message went out but the "published" mark was never written
    async with session_scope(rig.session_factory) as session:
        await session.execute(text("UPDATE events.correlation_groups SET publish_pending = true"))
    rig.clock.set(60)
    await rig.rebuild().sweeper.sweep()
    assert [m.revision for m in rig.publisher.messages] == [1, 1]  # a duplicate, never a gap


async def test_the_sweep_loop_outlives_failures_and_counts_them(rig, event) -> None:
    await rig.deliver(event("intrusion"))
    rig.publisher.fail_next = 3
    errors_before = sample("vms_correlation_sweep_errors_total")
    task = asyncio.create_task(rig.sweeper.run())
    try:
        await asyncio.wait_for(rig.publisher.published.wait(), timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)  # let an in-flight query unwind
    assert len(rig.publisher.messages) == 1
    assert sample("vms_correlation_sweep_errors_total") == errors_before + 3


async def test_a_hung_kafka_does_not_stall_event_handling(rig, event) -> None:
    await rig.deliver(event("intrusion"))
    release = asyncio.Event()
    entered = asyncio.Event()

    async def hang(message) -> None:
        entered.set()
        await release.wait()  # the broker never answers

    rig.publisher.publish = hang  # type: ignore[method-assign]
    sweep = asyncio.create_task(rig.sweeper.sweep())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)  # the sweeper is stuck mid-send
        # events still flow: grouping only needs the database
        await asyncio.wait_for(rig.deliver(event("running_skipped")), timeout=5)
        assert len(await groups(rig, "open")) == 1  # joined the first event's group
    finally:
        release.set()
        await asyncio.gather(sweep, return_exceptions=True)


async def test_closing_publishes_immediately_even_right_after_an_open_announcement(
    rig, event
) -> None:
    rig.clock.set(0)
    await rig.deliver(event("intrusion"))
    rig.clock.set(20)
    await rig.sweeper.sweep()
    assert [m.status for m in rig.publisher.messages] == ["open"]
    rig.clock.set(20 + 10_000)
    await rig.sweeper.sweep()
    assert [m.status for m in rig.publisher.messages] == ["open", "closed"]


async def test_each_message_carries_a_newer_revision_than_the_last_for_its_group(
    rig, event
) -> None:
    await deliver_scenario(rig, event)
    for t in (75, 90, 1000):
        rig.clock.set(t)
        await rig.sweeper.sweep()
    per_group: dict[str, list[int]] = {}
    for m in rig.publisher.messages:
        per_group.setdefault(m.group_id, []).append(m.revision)
    assert all(revs == sorted(set(revs)) for revs in per_group.values())


# --- metrics -----------------------------------------------------------------------------------


async def test_metrics_count_what_happened(rig, event) -> None:
    names = ("new_group", "joined", "merged")
    before = {n: sample("vms_correlation_events_total", result=n) for n in names}
    transit_before = sample("vms_correlation_links_total", edge_type="transit")
    closed_before = sample("vms_correlation_groups_closed_total")
    await deliver_scenario(rig, event)  # new_group, new_group, merged (with two links)
    after = {n: sample("vms_correlation_events_total", result=n) for n in names}
    assert [after[n] - before[n] for n in names] == [2, 0, 1]
    assert sample("vms_correlation_links_total", edge_type="transit") == transit_before + 2
    rig.clock.set(10_000)
    await rig.sweeper.sweep()
    assert sample("vms_correlation_groups_closed_total") == closed_before + 1
    assert sample("vms_correlation_open_groups_count") == 0


# --- concurrency -------------------------------------------------------------------------------


async def test_concurrent_deliveries_and_sweeps_leave_every_event_in_exactly_one_group(
    rig, event, fixture_topology
) -> None:
    events = [
        event(
            "intrusion",
            event_id=f"0192f3d1-00{i:02d}-7000-8000-0000000000{i:02d}",
            camera_id="cam02" if i % 2 else "cam03",  # cam02 and cam03 overlap: all of these link
            start_ts=(rig.clock.now + timedelta(seconds=i)).isoformat(),
            end_ts=(rig.clock.now + timedelta(seconds=i + 20)).isoformat(),
        )
        for i in range(1, 21)
    ]
    sweeps = [rig.sweeper.sweep() for _ in range(5)]
    await asyncio.gather(*(rig.deliver(e) for e in events), *sweeps)
    await rig.sweeper.sweep()

    held = [eid for g in await groups(rig) if g.status != "merged" for eid in g.event_ids]
    assert sorted(held) == sorted(e.event_id for e in events)  # none lost, none twice
    assert len(held) == len(set(held))
    async with session_scope(rig.session_factory) as session:
        links = (
            await session.execute(text("SELECT count(*) FROM events.correlation_links"))
        ).scalar_one()
    assert links >= 19  # at least a spanning set


async def test_a_merge_moves_the_absorbed_groups_links_to_the_survivor_in_the_database(
    rig_for, event
) -> None:
    from correlation.domain.topology import Topology  # noqa: PLC0415
    from vms_common.contracts.topology import TopologyEdgeInternal  # noqa: PLC0415

    def edge(i: int, a: str, b: str) -> TopologyEdgeInternal:
        return TopologyEdgeInternal(
            id=f"e{i}", from_camera_id=a, to_camera_id=b, edge_type="transit",
            min_s=5, max_s=90, bidirectional=False,
        )  # fmt: skip

    # two linked pairs (A->B, C->D) and a camera E that both pairs lead to
    graph = [
        edge(1, "camA", "camB"),
        edge(2, "camC", "camD"),
        edge(3, "camB", "camE"),
        edge(4, "camD", "camE"),
    ]
    rig = rig_for(Topology(graph))

    def stamp(seconds: int) -> str:
        return f"2026-10-05T10:{15 + seconds // 60}:{seconds % 60:02d}Z"

    def at(camera: str, start: int, end: int, n: int):
        return event(
            "intrusion",
            event_id=f"0192f3d1-00{n:02d}-7000-8000-0000000000{n:02d}",
            camera_id=camera,
            start_ts=stamp(start),
            end_ts=stamp(end),
        )

    pairs = [("camA", 0, 10), ("camB", 33, 40), ("camC", 0, 10), ("camD", 33, 40)]
    for n, (camera, start, end) in enumerate(pairs, start=1):
        rig.clock.set(start)
        await rig.deliver(at(camera, start, end, n))
    assert len(await groups(rig, "open")) == 2  # one group per linked pair, each with its link

    rig.clock.set(80)
    await rig.deliver(at("camE", 80, 90, 5))  # E follows both B (40 s later) and D: it bridges them

    (survivor,), (absorbed,) = await groups(rig, "open"), await groups(rig, "merged")
    assert len(survivor.members) == 5 and len(survivor.links) == 4
    assert absorbed.links == [] and absorbed.merged_into == survivor.id
    async with session_scope(rig.session_factory) as session:
        owners = (
            await session.execute(
                text("SELECT group_id::text, count(*) FROM events.correlation_links GROUP BY 1")
            )
        ).all()
    assert {(g, n) for g, n in owners} == {(survivor.id, 4)}  # all four links, all on the survivor
