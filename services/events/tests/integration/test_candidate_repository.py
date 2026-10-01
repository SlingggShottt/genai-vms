"""`events.candidates` upserts are idempotent and monotonic (P3-D1 AC:
"candidates persisted in events.candidates"; CLAUDE.md: idempotent consumer
writes). Needs Docker — run via `make test-int`."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from events.adapters.candidate_repository import upsert_candidates
from events.domain.candidates import CandidateUpdate
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_db.models import Candidate
from vms_db.session import session_scope

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 7, 0, 0, tzinfo=UTC)


def _update(**overrides) -> CandidateUpdate:
    fields = {
        "id": uuid.UUID("11111111-1111-5111-8111-111111111111"),
        "site_id": "rvce-campus",
        "camera_id": "cam01",
        "rule_id": "loitering",
        "event_type": "loitering",
        "severity": "medium",
        "zone_id": "zone01",
        "zone_name": "yard",
        "track_ids": ["cam01-t1"],
        "segment_ids": ["seg-000"],
        "start_ts": T0,
        "end_ts": T0 + timedelta(seconds=60),
        "rule_score": 0.7,
        "status": "open",
        "details": {"frames": 121, "duration_s": 60.0, "params": {"dwell_s": 60}},
    }
    fields.update(overrides)
    return CandidateUpdate(**fields)


async def _write(factory: async_sessionmaker, *updates: CandidateUpdate) -> list[CandidateUpdate]:
    async with session_scope(factory) as session:
        return await upsert_candidates(session, list(updates))


async def _row(factory: async_sessionmaker, candidate_id: uuid.UUID) -> Candidate:
    async with factory() as session:
        row = await session.get(Candidate, candidate_id)
        assert row is not None
        return row


async def _count(factory: async_sessionmaker) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(Candidate))).scalar_one()


@pytest.mark.asyncio
async def test_a_new_candidate_is_inserted_with_every_field(session_factory) -> None:
    created = await _write(session_factory, _update())

    row = await _row(session_factory, _update().id)
    assert [u.id for u in created] == [row.id]
    assert (row.site_id, row.camera_id, row.rule_id) == ("rvce-campus", "cam01", "loitering")
    assert (row.event_type, row.severity, row.status) == ("loitering", "medium", "open")
    assert (row.zone_id, row.zone_name) == ("zone01", "yard")
    assert row.track_ids == ["cam01-t1"]
    assert row.segment_ids == ["seg-000"]
    assert (row.start_ts, row.end_ts) == (T0, T0 + timedelta(seconds=60))
    assert row.rule_score == 0.7
    assert row.details == {"frames": 121, "duration_s": 60.0, "params": {"dwell_s": 60}}
    assert row.created_at is not None


@pytest.mark.asyncio
async def test_replaying_the_same_update_creates_nothing_new(session_factory) -> None:
    first = await _write(session_factory, _update())
    second = await _write(session_factory, _update())
    third = await _write(session_factory, _update())

    assert len(first) == 1
    assert (second, third) == ([], [])
    assert await _count(session_factory) == 1


@pytest.mark.asyncio
async def test_extending_a_candidate_moves_end_ts_and_unions_the_ids(session_factory) -> None:
    await _write(session_factory, _update())
    extended = _update(
        end_ts=T0 + timedelta(seconds=95),
        track_ids=["cam01-t1", "cam01-t4"],
        segment_ids=["seg-000", "seg-001"],
        rule_score=0.9,
        details={"frames": 191, "duration_s": 95.0},
    )

    created = await _write(session_factory, extended)

    row = await _row(session_factory, extended.id)
    assert created == []  # an extension is not a new candidate
    assert row.end_ts == T0 + timedelta(seconds=95)
    assert row.track_ids == ["cam01-t1", "cam01-t4"]
    assert row.segment_ids == ["seg-000", "seg-001"]
    assert row.rule_score == 0.9
    assert row.details["frames"] == 191
    assert await _count(session_factory) == 1


@pytest.mark.asyncio
async def test_an_older_update_arriving_late_cannot_shrink_or_overwrite_a_candidate(
    session_factory,
) -> None:
    await _write(
        session_factory,
        _update(end_ts=T0 + timedelta(seconds=95), rule_score=0.9, details={"duration_s": 95.0}),
    )

    await _write(
        session_factory,
        _update(end_ts=T0 + timedelta(seconds=60), rule_score=0.5, details={"duration_s": 60.0}),
    )

    row = await _row(session_factory, _update().id)
    assert row.end_ts == T0 + timedelta(seconds=95)
    assert row.rule_score == 0.9
    assert row.details == {"duration_s": 95.0}


@pytest.mark.asyncio
async def test_closing_is_final_and_a_late_open_update_cannot_reopen_it(session_factory) -> None:
    await _write(session_factory, _update(status="open"))
    await _write(session_factory, _update(status="closed", end_ts=T0 + timedelta(seconds=80)))

    await _write(session_factory, _update(status="open", end_ts=T0 + timedelta(seconds=70)))

    row = await _row(session_factory, _update().id)
    assert row.status == "closed"
    assert row.end_ts == T0 + timedelta(seconds=80)


@pytest.mark.asyncio
async def test_segment_ids_are_merged_without_duplicates_and_sorted(session_factory) -> None:
    await _write(session_factory, _update(segment_ids=["seg-002", "seg-000"]))

    await _write(session_factory, _update(segment_ids=["seg-001", "seg-002"]))

    row = await _row(session_factory, _update().id)
    assert row.segment_ids == ["seg-000", "seg-001", "seg-002"]


@pytest.mark.asyncio
async def test_several_candidates_in_one_batch_are_all_written(session_factory) -> None:
    a = _update()
    b = replace(
        a,
        id=uuid.UUID("22222222-2222-5222-8222-222222222222"),
        rule_id="crowding",
        event_type="crowding",
        zone_name="plaza",
        zone_id=None,
        track_ids=[],
    )

    created = await _write(session_factory, a, b)

    assert {u.id for u in created} == {a.id, b.id}
    assert (await _row(session_factory, b.id)).zone_id is None
    assert (await _row(session_factory, b.id)).track_ids == []


@pytest.mark.asyncio
async def test_a_bad_row_rolls_the_whole_batch_back(session_factory) -> None:
    good = _update()
    bad = replace(
        good, id=uuid.UUID("33333333-3333-5333-8333-333333333333"), severity="catastrophic"
    )

    with pytest.raises(IntegrityError):
        await _write(session_factory, good, bad)

    assert await _count(session_factory) == 0


@pytest.mark.asyncio
async def test_the_database_enforces_the_status_values(session_factory) -> None:
    with pytest.raises(IntegrityError):
        await _write(session_factory, _update(status="pending"))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_updated_at_moves_when_a_candidate_is_extended(session_factory) -> None:
    await _write(session_factory, _update())
    before = (await _row(session_factory, _update().id)).updated_at

    async with session_factory() as session:
        await session.execute(text("SELECT pg_sleep(0.05)"))
    await _write(session_factory, _update(end_ts=T0 + timedelta(seconds=70)))

    after = (await _row(session_factory, _update().id)).updated_at
    assert after > before
