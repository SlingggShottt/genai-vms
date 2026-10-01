"""The events consumer end to end against a real Postgres: twin in, candidate
rows out, and the at-least-once safety properties (replay, crash between the
database write and the state checkpoint, restart). Needs Docker — run via
`make test-int`."""

from __future__ import annotations

from datetime import timedelta

import pytest
from events.adapters.state_store import MemoryStateStore
from events.domain.config import RulesConfig
from events.domain.state import CameraState
from events.metrics import candidates_total
from events.worker import EventsConsumer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.contracts.twin import TwinV1
from vms_common.contracts.twinready import TwinReadyV1
from vms_db.models import Candidate

pytestmark = pytest.mark.integration


class FakeS3:
    """Just the one method the consumer uses: `get_bytes(uri)`."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, twin: TwinV1) -> str:
        uri = f"s3://vms-twins/{twin.camera_id}/{twin.segment_id}.json"
        self.objects[uri] = twin.model_dump_json().encode()
        return uri

    async def get_bytes(self, uri: str) -> bytes:
        return self.objects[uri]


class FlakyStateStore(MemoryStateStore):
    """Fails its next `failures_left` saves — a crash after the database write, before the
    checkpoint. Starts healthy; the test arms it."""

    def __init__(self) -> None:
        super().__init__()
        self.failures_left = 0

    async def save(self, state: CameraState) -> None:
        if self.failures_left:
            self.failures_left -= 1
            raise ConnectionError("redis went away")
        await super().save(state)


def _consumer(session_factory, s3, state_store, zones, make, config=None) -> EventsConsumer:
    return EventsConsumer(
        topic="vms.twin.v1",
        group_id="events-test",
        bootstrap_servers="unused:9092",  # never started: handle() is called directly
        model=TwinReadyV1,
        s3=s3,
        session_factory=session_factory,
        state_store=state_store,
        get_zones=lambda: zones,
        config=config or RulesConfig(),
        site_tz=make.IST,
    )


def _message(twin: TwinV1, uri: str) -> TwinReadyV1:
    return TwinReadyV1(
        site_id=twin.site_id,
        camera_id=twin.camera_id,
        segment_id=twin.segment_id,
        start_ts=twin.start_ts,
        end_ts=twin.end_ts,
        twin_uri=uri,
        embeddings_uri=uri.replace(".json", ".npz"),
        sample_fps=twin.sample_fps,
        perception_version="test@0",
    )


async def _deliver(consumer: EventsConsumer, s3: FakeS3, twins: list[TwinV1]) -> None:
    for twin in twins:
        await consumer.handle(_message(twin, s3.put(twin)), record=None)  # type: ignore[arg-type]


async def _candidates(factory: async_sessionmaker) -> list[Candidate]:
    async with factory() as session:
        return list(
            (await session.execute(select(Candidate).order_by(Candidate.start_ts))).scalars()
        )


async def _count(factory: async_sessionmaker) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(Candidate))).scalar_one()


def _stay(make, seconds: float = 65, total_s: float = 90) -> list[TwinV1]:
    """One person standing in the generic zone "yard" for `seconds`."""
    return make.twins(
        make.frames(seconds, [make.obj("cam01-t1", zones=("yard",))]), total_s=total_s
    )


@pytest.mark.asyncio
async def test_a_loitering_stay_becomes_one_candidate_row(session_factory, make) -> None:
    s3, store = FakeS3(), MemoryStateStore()
    consumer = _consumer(session_factory, s3, store, [make.zone("yard", "generic")], make)
    before = candidates_total.labels(rule="loitering")._value.get()

    await _deliver(consumer, s3, _stay(make))

    (row,) = await _candidates(session_factory)
    assert (row.rule_id, row.event_type, row.severity) == ("loitering", "loitering", "medium")
    assert (row.camera_id, row.site_id, row.zone_name) == ("cam01", "rvce-campus", "yard")
    assert row.track_ids == ["cam01-t1"]
    assert row.start_ts == make.T0
    assert row.status == "closed"  # the person left and a quiet segment followed
    assert len(row.segment_ids) == 7  # the stay touched seven 10 s segments
    assert candidates_total.labels(rule="loitering")._value.get() == before + 1
    saved = await store.load("cam01")
    assert saved is not None and saved.last_segment_end is not None


@pytest.mark.asyncio
async def test_redelivering_the_last_message_changes_nothing(session_factory, make) -> None:
    s3, store = FakeS3(), MemoryStateStore()
    consumer = _consumer(session_factory, s3, store, [make.zone("yard", "generic")], make)
    twins = _stay(make)
    await _deliver(consumer, s3, twins)
    rows_before = [
        (r.id, r.end_ts, r.status, r.updated_at) for r in await _candidates(session_factory)
    ]
    metric_before = candidates_total.labels(rule="loitering")._value.get()

    await _deliver(consumer, s3, twins[-1:])  # Kafka redelivers the last twin

    assert [
        (r.id, r.end_ts, r.status, r.updated_at) for r in await _candidates(session_factory)
    ] == rows_before
    assert candidates_total.labels(rule="loitering")._value.get() == metric_before


@pytest.mark.asyncio
async def test_replaying_every_twin_after_losing_the_saved_state_does_not_duplicate_rows(
    session_factory, make
) -> None:
    s3 = FakeS3()
    twins = _stay(make)
    zones = [make.zone("yard", "generic")]
    await _deliver(_consumer(session_factory, s3, MemoryStateStore(), zones, make), s3, twins)
    first = {r.id: (r.start_ts, r.end_ts, r.status) for r in await _candidates(session_factory)}

    # Redis was flushed AND the consumer group was reset: everything replays from scratch.
    await _deliver(_consumer(session_factory, s3, MemoryStateStore(), zones, make), s3, twins)

    assert {
        r.id: (r.start_ts, r.end_ts, r.status) for r in await _candidates(session_factory)
    } == first
    assert len(first) == 1


@pytest.mark.asyncio
async def test_a_crash_between_the_database_write_and_the_checkpoint_is_recovered(
    session_factory, make
) -> None:
    s3, store = FakeS3(), FlakyStateStore()
    zones = [make.zone("yard", "generic")]
    consumer = _consumer(session_factory, s3, store, zones, make)
    twins = _stay(make)
    await _deliver(consumer, s3, twins[:6])  # the 7th twin is the one that creates the candidate
    assert await _count(session_factory) == 0

    store.failures_left = 1
    with pytest.raises(ConnectionError):
        await _deliver(consumer, s3, twins[6:7])
    assert await _count(session_factory) == 1  # written before the checkpoint failed

    await _deliver(consumer, s3, twins[6:])  # redelivery of that twin, then the rest

    rows = await _candidates(session_factory)
    assert len(rows) == 1
    assert rows[0].status == "closed"
    assert rows[0].end_ts == make.T0 + timedelta(seconds=65)


@pytest.mark.asyncio
async def test_state_is_not_saved_if_writing_the_candidates_fails(
    session_factory, make, monkeypatch
) -> None:
    import events.worker as worker

    async def boom(session, updates):
        raise ConnectionError("database went away")

    s3, store = FakeS3(), MemoryStateStore()
    consumer = _consumer(session_factory, s3, store, [make.zone("yard", "generic")], make)
    twins = _stay(make)
    await _deliver(consumer, s3, twins[:6])
    saved_before = (await store.load("cam01")).model_dump_json()

    monkeypatch.setattr(worker, "upsert_candidates", boom)
    with pytest.raises(ConnectionError):
        await _deliver(consumer, s3, twins[6:7])

    assert (await store.load("cam01")).model_dump_json() == saved_before  # still the old state


@pytest.mark.asyncio
async def test_a_restarted_consumer_resumes_a_stay_from_the_saved_state(
    session_factory, make
) -> None:
    s3, store = FakeS3(), MemoryStateStore()  # the store outlives the consumer, like Redis
    zones = [make.zone("yard", "generic")]
    twins = _stay(make, seconds=95, total_s=120)

    await _deliver(_consumer(session_factory, s3, store, zones, make), s3, twins[:4])  # 40 s in
    await _deliver(_consumer(session_factory, s3, store, zones, make), s3, twins[4:])  # "restart"

    (row,) = await _candidates(session_factory)
    assert row.start_ts == make.T0  # the stay's real start, not the restart point
    assert row.details["duration_s"] == 95.0


@pytest.mark.asyncio
async def test_no_zones_means_no_candidates_but_the_state_still_advances(
    session_factory, make
) -> None:
    s3, store = FakeS3(), MemoryStateStore()
    consumer = _consumer(session_factory, s3, store, [], make)  # e.g. zones.yaml not found yet

    await _deliver(consumer, s3, _stay(make))

    assert await _count(session_factory) == 0
    saved = await store.load("cam01")
    assert saved is not None and saved.last_segment_end is not None


@pytest.mark.asyncio
async def test_each_camera_is_evaluated_with_its_own_state(session_factory, make) -> None:
    s3, store = FakeS3(), MemoryStateStore()
    zones = [
        make.zone("yard", "restricted", camera_id="cam01"),
        make.zone("yard", "restricted", camera_id="cam02"),
    ]
    consumer = _consumer(session_factory, s3, store, zones, make)
    cam1 = make.twins(make.frames(3, [make.obj("cam01-t1")]), camera_id="cam01", total_s=20)
    cam2 = make.twins(make.frames(3, [make.obj("cam02-t1")]), camera_id="cam02", total_s=20)

    await _deliver(consumer, s3, [cam1[0], cam2[0], cam1[1], cam2[1]])  # interleaved cameras

    rows = await _candidates(session_factory)
    assert sorted(r.camera_id for r in rows) == ["cam01", "cam02"]
    assert {(await store.load(c)).camera_id for c in ("cam01", "cam02")} == {"cam01", "cam02"}


# --- camera-wide rules (P3-D2): no zones, a back-dated start, a scratchpad in the state ---------


def _bag_and_owner(make, seconds: float, owner_leaves_at: float) -> list[tuple[float, list]]:
    """A backpack at rest in the middle of the frame; its owner stands beside it, then walks off."""
    specs = []
    for i in range(round(seconds * 2) + 1):
        t = i / 2
        owner_at = (0.52, 0.5) if t < owner_leaves_at else (0.9, 0.5)
        specs.append(
            (
                t,
                [
                    make.obj("cam01-t50", "backpack", zones=(), center=(0.5, 0.5)),
                    make.obj("cam01-t1", "person", zones=(), center=owner_at),
                ],
            )
        )
    return specs


@pytest.mark.asyncio
async def test_an_abandoned_bag_becomes_a_candidate_with_no_zone(session_factory, make) -> None:
    s3, store = FakeS3(), MemoryStateStore()
    consumer = _consumer(session_factory, s3, store, [], make)  # no zones configured at all
    twins = make.twins(_bag_and_owner(make, 45, owner_leaves_at=10), total_s=70)

    await _deliver(consumer, s3, twins)

    rows = [r for r in await _candidates(session_factory) if r.rule_id == "abandoned_object"]
    (row,) = rows
    assert (row.event_type, row.severity) == ("abandoned_object", "high")
    assert (row.zone_id, row.zone_name) == (None, None)  # NULL columns round-trip
    assert row.track_ids == ["cam01-t50"]
    assert row.start_ts == make.T0 + timedelta(seconds=10)  # back-dated to when the owner left
    assert row.end_ts == make.T0 + timedelta(seconds=45)
    assert row.status == "closed"
    assert row.details["peak_unattended_s"] >= 20


@pytest.mark.asyncio
async def test_a_restart_mid_wait_keeps_the_bags_clock_through_the_saved_state(
    session_factory, make
) -> None:
    s3, store = FakeS3(), MemoryStateStore()  # the store outlives the consumer, like Redis
    twins = make.twins(_bag_and_owner(make, 75, owner_leaves_at=10), total_s=100)

    await _deliver(_consumer(session_factory, s3, store, [], make), s3, twins[:2])  # 20 s in
    saved = await store.load("cam01")
    assert saved is not None and "abandoned_object" in saved.memory  # the scratchpad was saved
    assert await _count(session_factory) == 0

    await _deliver(_consumer(session_factory, s3, store, [], make), s3, twins[2:])  # "restart"

    (row,) = [r for r in await _candidates(session_factory) if r.rule_id == "abandoned_object"]
    assert row.start_ts == make.T0 + timedelta(seconds=10)  # not 20: the restart didn't reset it


@pytest.mark.asyncio
async def test_running_needs_no_zones_and_is_stored_without_one(session_factory, make) -> None:
    s3, store = FakeS3(), MemoryStateStore()
    consumer = _consumer(session_factory, s3, store, [], make)
    runner = [make.obj("cam01-t9", zones=(), speed=0.6)]
    twins = make.twins(make.frames(3, runner), total_s=30)

    await _deliver(consumer, s3, twins)

    (row,) = [r for r in await _candidates(session_factory) if r.rule_id == "running"]
    assert (row.event_type, row.severity) == ("running", "low")
    assert (row.zone_id, row.zone_name) == (None, None)
    assert row.details["peak_speed"] == 0.6


@pytest.mark.asyncio
async def test_replaying_camera_wide_candidates_does_not_duplicate_them(
    session_factory, make
) -> None:
    s3 = FakeS3()
    twins = make.twins(_bag_and_owner(make, 45, owner_leaves_at=10), total_s=70)
    await _deliver(_consumer(session_factory, s3, MemoryStateStore(), [], make), s3, twins)
    before = {r.id: (r.start_ts, r.end_ts, r.status) for r in await _candidates(session_factory)}

    # everything replays from nothing, e.g. Redis flushed and the consumer group reset
    await _deliver(_consumer(session_factory, s3, MemoryStateStore(), [], make), s3, twins)

    assert {
        r.id: (r.start_ts, r.end_ts, r.status) for r in await _candidates(session_factory)
    } == before
