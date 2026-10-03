"""The group repository against real Postgres (P3-J2: persistence of groups and links)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from correlation.adapters import group_repository as repo
from correlation.domain.types import EventRecord, Group, LinkRecord
from sqlalchemy import text
from vms_db.session import session_scope

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def event(camera: str = "cam02", start: float = 0, end: float = 10, **kw: object) -> EventRecord:
    return EventRecord(
        event_id=str(kw.get("event_id") or uuid.uuid4()),
        site_id=str(kw.get("site_id", "site")),
        camera_id=camera,
        event_type=str(kw.get("event_type", "intrusion")),
        severity=str(kw.get("severity", "high")),
        start_ts=NOW + timedelta(seconds=start),
        end_ts=NOW + timedelta(seconds=end),
    )


def group(*members: EventRecord, **kw: object) -> Group:
    return Group(
        id=str(kw.pop("id", uuid.uuid4())),  # type: ignore[arg-type]
        site_id=members[0].site_id,
        created_at=NOW,
        members=list(members),
        **kw,  # type: ignore[arg-type]
    )


async def test_a_group_round_trips_with_members_links_and_state(session_factory) -> None:
    a, b = event("cam02", 0, 10, severity="medium"), event("cam04", 33, 40, severity="critical")
    original = group(
        a,
        b,
        revision=4,
        links=[LinkRecord(a.event_id, b.event_id, "transit", 23.0, 0.5365)],
        publish_pending=False,
        last_published_at=NOW + timedelta(seconds=7),
    )
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [original])
    async with session_scope(session_factory) as session:
        loaded = await repo.get_group(session, original.id)

    assert loaded is not None
    assert (loaded.id, loaded.site_id, loaded.status, loaded.revision) == (
        original.id, "site", "open", 4,
    )  # fmt: skip
    assert loaded.members == [a, b]  # same order, same timestamps, timezone-aware
    assert loaded.links == original.links
    assert loaded.max_severity == "critical" and loaded.camera_ids == ["cam02", "cam04"]
    assert (loaded.start_ts, loaded.end_ts) == (a.start_ts, b.end_ts)
    assert (
        loaded.publish_pending is False and loaded.last_published_at == original.last_published_at
    )
    assert loaded.created_at == NOW and loaded.closed_at is None and loaded.merged_into is None
    assert loaded.start_ts.tzinfo is not None


async def test_get_group_of_an_unknown_id_is_none(session_factory) -> None:
    async with session_scope(session_factory) as session:
        assert await repo.get_group(session, str(uuid.uuid4())) is None


async def test_event_already_grouped_sees_open_closed_and_merged_groups(session_factory) -> None:
    open_e, closed_e, merged_e = event(), event(), event()
    survivor = group(event())
    groups = [
        group(open_e),
        group(closed_e, status="closed", closed_at=NOW),
        group(merged_e, status="merged", merged_into=survivor.id, closed_at=NOW),
        survivor,
    ]
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [survivor, *groups[:3]])  # survivor first (FK)
    async with session_scope(session_factory) as session:
        for member in (open_e, closed_e, merged_e):
            assert await repo.event_already_grouped(session, member.event_id), member.event_id
        assert not await repo.event_already_grouped(session, str(uuid.uuid4()))


async def test_load_open_groups_returns_only_open_ones_optionally_for_one_site(
    session_factory,
) -> None:
    north, south, closed = (
        group(event(site_id="north")),
        group(event(site_id="south")),
        group(event(site_id="north"), status="closed", closed_at=NOW),
    )
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [north, south, closed])
    async with session_scope(session_factory) as session:
        everything = await repo.load_open_groups(session)
        only_north = await repo.load_open_groups(session, site_id="north")
    assert {g.id for g in everything} == {north.id, south.id}
    assert [g.id for g in only_north] == [north.id]


async def test_open_groups_load_oldest_first(session_factory) -> None:
    older, newer = group(event()), group(event())
    older.created_at, newer.created_at = NOW, NOW + timedelta(seconds=5)
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [newer, older])
    async with session_scope(session_factory) as session:
        assert [g.id for g in await repo.load_open_groups(session)] == [older.id, newer.id]


async def test_an_older_revision_never_overwrites_a_newer_one(session_factory) -> None:
    a, b = event(), event("cam04")
    current = group(a, b, revision=3)
    stale = group(a, id=current.id, revision=2)
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [current])
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [stale])  # a stale writer
    async with session_scope(session_factory) as session:
        loaded = await repo.get_group(session, current.id)
    assert loaded is not None and loaded.revision == 3 and len(loaded.members) == 2


async def test_a_newer_revision_replaces_the_row(session_factory) -> None:
    a, b = event(), event("cam04")
    g = group(a, revision=1)
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [g])
    g.members.append(b)
    g.revision = 2
    g.status = "closed"
    g.closed_at = NOW
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [g])
    async with session_scope(session_factory) as session:
        loaded = await repo.get_group(session, g.id)
    assert loaded is not None and (loaded.revision, loaded.status) == (2, "closed")
    assert loaded.event_ids == [a.event_id, b.event_id] and loaded.closed_at == NOW


async def test_saving_the_same_links_twice_does_not_duplicate_them(session_factory) -> None:
    a, b = event(), event("cam04")
    g = group(a, b, links=[LinkRecord(a.event_id, b.event_id, "transit", 23.0, 0.54)])
    for revision in (1, 2):
        g.revision = revision
        async with session_scope(session_factory) as session:
            await repo.save_groups(session, [g])
    async with session_scope(session_factory) as session:
        count = (
            await session.execute(text("SELECT count(*) FROM events.correlation_links"))
        ).scalar_one()
    assert count == 1


async def test_a_merge_repoints_the_absorbed_groups_links_at_the_survivor(session_factory) -> None:
    a, b, c, d = event("a"), event("b"), event("c"), event("d")
    survivor = group(a, b, links=[LinkRecord(a.event_id, b.event_id, "transit", 20.0, 0.6)])
    absorbed = group(c, d, links=[LinkRecord(c.event_id, d.event_id, "transit", 30.0, 0.7)])
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [survivor, absorbed])

    # the engine's merge: the absorbed group's links move to the survivor, which gains its members
    survivor.members += absorbed.members
    survivor.links += absorbed.links
    absorbed.links = []
    absorbed.status, absorbed.merged_into, absorbed.closed_at = "merged", survivor.id, NOW
    survivor.revision = absorbed.revision = 2
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [survivor, absorbed])

    async with session_scope(session_factory) as session:
        rows = (
            await session.execute(
                text("SELECT group_id::text, count(*) FROM events.correlation_links GROUP BY 1")
            )
        ).all()
        loaded = await repo.get_group(session, survivor.id)
        gone = await repo.get_group(session, absorbed.id)
    assert {(gid, n) for gid, n in rows} == {(survivor.id, 2)}  # both links, none left behind
    assert loaded is not None and len(loaded.links) == 2 and len(loaded.members) == 4
    assert gone is not None and gone.status == "merged" and gone.merged_into == survivor.id
    assert gone.links == []


async def test_pending_groups_are_those_with_an_unannounced_change(session_factory) -> None:
    pending, sent = group(event()), group(event(), publish_pending=False)
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [pending, sent])
    async with session_scope(session_factory) as session:
        assert [g.id for g in await repo.load_pending_groups(session)] == [pending.id]


async def test_mark_published_clears_the_flag_only_for_the_revision_that_went_out(
    session_factory,
) -> None:
    g = group(event(), revision=2)
    async with session_scope(session_factory) as session:
        await repo.save_groups(session, [g])

    async with session_scope(session_factory) as session:  # an older revision was sent
        await repo.mark_published(session, g.id, revision=1, now=NOW)
    async with session_scope(session_factory) as session:
        loaded = await repo.get_group(session, g.id)
    assert loaded is not None and loaded.publish_pending and loaded.last_published_at == NOW

    async with session_scope(session_factory) as session:  # the current one was sent
        await repo.mark_published(session, g.id, revision=2, now=NOW + timedelta(seconds=9))
    async with session_scope(session_factory) as session:
        loaded = await repo.get_group(session, g.id)
    assert loaded is not None and not loaded.publish_pending
    assert loaded.last_published_at == NOW + timedelta(seconds=9)
