"""The VLM gate's queue and outbox against a real Postgres (P3-D4): who gets claimed, when, how
two workers share the work, and that a decision is written once and announced until it is.
Needs Docker — run via `make test-int`."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from events.adapters.candidate_repository import upsert_candidates
from events.adapters.event_store import PostgresEventStore
from events.domain.candidates import CandidateUpdate
from events.domain.config import RulesConfig
from events.domain.evidence import EvidenceBox, EvidenceFrame
from events.domain.records import EventRow
from events.verifier import Verifier, VerifierOptions
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.contracts.event import EventV1
from vms_common.llm import LLMUnavailableError
from vms_common.llm.testing import FakeGateway
from vms_db.session import session_scope

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)
LEASE_S = 120.0
OPEN_AFTER_S = 90.0
MAX_AGE_S = 6 * 3600.0
YES = {"verdict": "yes", "confidence": 0.9, "caption": "A person climbs the gate."}


def evidence(n: int = 3) -> list[dict]:
    return [
        EvidenceFrame(
            ts=NOW - timedelta(seconds=40 - 5 * i),
            segment_id="cam01_seg",
            keyframe_uri=f"s3://vms-keyframes/cam01/{i:04d}.jpg",
            boxes=[EvidenceBox(track_id="cam01-t1", category="person", bbox=(0.2, 0.2, 0.6, 0.9))],
        ).model_dump(mode="json")
        for i in range(n)
    ]


def update(**overrides) -> CandidateUpdate:  # noqa: ANN003
    fields = {
        "id": uuid.uuid4(),
        "site_id": "rvce-campus",
        "camera_id": "cam01",
        "rule_id": "intrusion.restricted",
        "event_type": "intrusion",
        "severity": "high",
        "zone_id": "zone01",
        "zone_name": "yard",
        "track_ids": ["cam01-t1"],
        "segment_ids": ["cam01_seg"],
        "start_ts": NOW - timedelta(seconds=40),
        "end_ts": NOW - timedelta(seconds=10),
        "rule_score": 0.9,
        "status": "closed",
        "details": {"frames": 7, "evidence": evidence()},
    }
    fields.update(overrides)
    return CandidateUpdate(**fields)


async def add(factory: async_sessionmaker, *updates: CandidateUpdate) -> None:
    async with session_scope(factory) as session:
        await upsert_candidates(session, list(updates))


async def sql(factory: async_sessionmaker, statement: str, **params: object) -> list:
    async with session_scope(factory) as session:
        result = await session.execute(text(statement), params)
        return list(result.mappings().all()) if result.returns_rows else []


def claim_args(**overrides: object) -> dict:
    args = {
        "now": NOW,
        "limit": 10,
        "lease_s": LEASE_S,
        "open_after_s": OPEN_AFTER_S,
        "max_age_s": MAX_AGE_S,
    }
    return args | overrides


def row_for(candidate: CandidateUpdate, **overrides) -> EventRow:  # noqa: ANN003
    fields = {
        "id": candidate.id,
        "site_id": candidate.site_id,
        "camera_id": candidate.camera_id,
        "event_type": candidate.event_type,
        "severity": candidate.severity,
        "rule_id": candidate.rule_id,
        "rule_score": candidate.rule_score,
        "zone_id": candidate.zone_id,
        "zone_name": candidate.zone_name,
        "track_ids": candidate.track_ids,
        "segment_ids": candidate.segment_ids,
        "keyframe_uris": ["s3://vms-keyframes/cam01/0000.jpg"],
        "start_ts": candidate.start_ts,
        "end_ts": candidate.end_ts,
        "status": "verified",
        "verification": {"status": "verified", "confidence": 0.9, "caption": "A person."},
    }
    return EventRow(**(fields | overrides))


class TestClaiming:
    async def test_a_closed_candidate_is_claimed_whole_and_marked_as_tried(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        store = PostgresEventStore(session_factory)

        [claimed] = await store.claim(**claim_args())

        assert claimed.id == c.id and claimed.rule_id == "intrusion.restricted"
        assert (claimed.severity, claimed.zone_name, claimed.track_ids) == (
            "high",
            "yard",
            ["cam01-t1"],
        )
        assert claimed.status == "closed" and claimed.rule_score == pytest.approx(0.9)
        assert (claimed.attempts, claimed.first_at) == (1, NOW)
        assert [f.keyframe_uri for f in claimed.evidence] == [
            f"s3://vms-keyframes/cam01/{i:04d}.jpg" for i in range(3)
        ]
        assert claimed.evidence[0].boxes[0].bbox == pytest.approx((0.2, 0.2, 0.6, 0.9))
        [stored] = await sql(
            session_factory,
            "SELECT verify_attempts, verify_first_at, verify_not_before FROM events.candidates",
        )
        assert stored["verify_attempts"] == 1
        assert stored["verify_not_before"] == NOW + timedelta(seconds=LEASE_S)

    async def test_a_candidate_still_going_waits_until_it_has_been_one_for_a_while(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update(status="open")
        await add(session_factory, c)
        # "How long it has been a candidate" is the row's created_at, which the database stamps
        # with the real clock; the test's clock is NOW, so line them up (else the test passes only
        # when it runs within five seconds of being imported, and a cold container takes longer).
        await sql(
            session_factory,
            "UPDATE events.candidates SET created_at = :at WHERE id = :id",
            at=NOW,
            id=c.id,
        )
        store = PostgresEventStore(session_factory)
        assert await store.claim(**claim_args(now=NOW)) == [], "it only just became a candidate"
        assert await store.claim(**claim_args(now=NOW + timedelta(seconds=OPEN_AFTER_S - 5))) == []

        [claimed] = await store.claim(**claim_args(now=NOW + timedelta(seconds=OPEN_AFTER_S + 5)))
        assert claimed.id == c.id and claimed.status == "open"

    async def test_a_claimed_candidate_is_hidden_until_its_lease_runs_out(
        self, session_factory: async_sessionmaker
    ) -> None:
        await add(session_factory, update())
        store = PostgresEventStore(session_factory)
        [first] = await store.claim(**claim_args())

        assert await store.claim(**claim_args()) == []
        assert await store.claim(**claim_args(now=NOW + timedelta(seconds=LEASE_S - 1))) == []

        [again] = await store.claim(**claim_args(now=NOW + timedelta(seconds=LEASE_S + 1)))
        assert again.id == first.id
        assert (again.attempts, again.first_at) == (2, NOW), "tried twice; the first try is kept"

    async def test_a_back_off_hides_it_until_then(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        store = PostgresEventStore(session_factory)
        await store.claim(**claim_args())
        await store.reschedule(c.id, NOW + timedelta(seconds=20))

        assert await store.claim(**claim_args(now=NOW + timedelta(seconds=19))) == []
        [again] = await store.claim(**claim_args(now=NOW + timedelta(seconds=21)))
        assert again.attempts == 2

    async def test_a_candidate_with_a_decision_is_never_offered_again(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        store = PostgresEventStore(session_factory)
        await store.save_event(row_for(c, status="rejected", verification={"status": "rejected"}))

        assert await store.claim(**claim_args(now=NOW + timedelta(days=1), max_age_s=10**9)) == []

    async def test_a_candidate_that_ended_long_ago_is_left_alone(
        self, session_factory: async_sessionmaker
    ) -> None:
        stale = update(end_ts=NOW - timedelta(seconds=MAX_AGE_S + 60))
        fresh = update(end_ts=NOW - timedelta(seconds=MAX_AGE_S - 60))
        await add(session_factory, stale, fresh)

        claimed = await PostgresEventStore(session_factory).claim(**claim_args())
        assert [c.id for c in claimed] == [fresh.id]

    async def test_the_most_severe_comes_first_then_the_oldest_and_a_batch_is_no_bigger_than_asked(
        self, session_factory: async_sessionmaker
    ) -> None:
        low = update(severity="low", end_ts=NOW - timedelta(seconds=300))
        old_high = update(severity="high", end_ts=NOW - timedelta(seconds=200))
        new_high = update(severity="high", end_ts=NOW - timedelta(seconds=20))
        critical = update(severity="critical", end_ts=NOW - timedelta(seconds=5))
        medium = update(severity="medium", end_ts=NOW - timedelta(seconds=100))
        await add(session_factory, low, old_high, new_high, critical, medium)
        store = PostgresEventStore(session_factory)

        first = await store.claim(**claim_args(limit=3))
        assert [c.id for c in first] == [critical.id, old_high.id, new_high.id]
        rest = await store.claim(**claim_args(limit=3))
        assert [c.id for c in rest] == [medium.id, low.id]

    async def test_workers_running_at_once_never_share_a_candidate(
        self, session_factory: async_sessionmaker
    ) -> None:
        candidates = [update() for _ in range(8)]
        await add(session_factory, *candidates)
        store = PostgresEventStore(session_factory)

        batches = await asyncio.gather(*(store.claim(**claim_args(limit=3)) for _ in range(6)))

        claimed = [c.id for batch in batches for c in batch]
        assert len(claimed) == len(set(claimed)) == 8
        assert set(claimed) == {c.id for c in candidates}


class TestDecisions:
    async def test_a_decision_is_written_once_and_the_first_one_stands(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        store = PostgresEventStore(session_factory)

        assert await store.save_event(row_for(c)) is True
        assert await store.save_event(row_for(c, status="rejected")) is False

        [stored] = await sql(session_factory, "SELECT status, verification FROM events.events")
        assert stored["status"] == "verified"
        assert stored["verification"] == {
            "status": "verified",
            "confidence": 0.9,
            "caption": "A person.",
        }

    async def test_what_is_written_comes_back_unchanged(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update(track_ids=["cam01-t1", "cam01-t9"])
        await add(session_factory, c)
        store = PostgresEventStore(session_factory)
        written = row_for(
            c,
            keyframe_uris=["s3://vms-keyframes/a.jpg", "s3://vms-keyframes/b.jpg"],
            verification={"status": "verified", "frames": 2, "model": "ollama/qwen2.5vl:3b"},
        )
        await store.save_event(written)

        [read] = await store.unpublished(limit=10)
        assert read == written


class TestTheOutbox:
    async def test_lists_verified_and_skipped_never_rejected_and_ticks_off_what_was_sent(
        self, session_factory: async_sessionmaker
    ) -> None:
        a, b, c = update(), update(), update()
        await add(session_factory, a, b, c)
        store = PostgresEventStore(session_factory)
        await store.save_event(row_for(a, status="verified"))
        await store.save_event(row_for(b, status="skipped", verification={"status": "skipped"}))
        await store.save_event(row_for(c, status="rejected", verification={"status": "rejected"}))

        assert {r.id for r in await store.unpublished(limit=10)} == {a.id, b.id}

        await store.mark_published(a.id, NOW)
        assert [r.id for r in await store.unpublished(limit=10)] == [b.id]

    async def test_marking_twice_keeps_the_first_time(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        store = PostgresEventStore(session_factory)
        await store.save_event(row_for(c))
        await store.mark_published(c.id, NOW)
        await store.mark_published(c.id, NOW + timedelta(hours=1))

        [stored] = await sql(session_factory, "SELECT published_at FROM events.events")
        assert stored["published_at"] == NOW

    async def test_the_oldest_decision_goes_first_and_a_batch_is_bounded(
        self, session_factory: async_sessionmaker
    ) -> None:
        candidates = [update() for _ in range(3)]
        await add(session_factory, *candidates)
        store = PostgresEventStore(session_factory)
        for candidate in candidates:
            await store.save_event(row_for(candidate))
            await asyncio.sleep(0.01)  # created_at orders them

        assert [r.id for r in await store.unpublished(limit=2)] == [c.id for c in candidates[:2]]


@dataclass
class Keyframes:
    async def load(self, frames: list[EvidenceFrame]) -> list[tuple[EvidenceFrame, bytes]]:
        out = BytesIO()
        Image.new("RGB", (448, 252), (0, 0, 255)).save(out, format="JPEG")
        return [(f, out.getvalue()) for f in frames]


@dataclass
class Publisher:
    events: list[EventV1] = field(default_factory=list)
    failing: bool = False

    async def publish(self, event: EventV1) -> None:
        if self.failing:
            raise ConnectionError("kafka is down")
        self.events.append(event)


class TestTheGateOnARealDatabase:
    def verifier(
        self, factory: async_sessionmaker, gateway: FakeGateway, publisher: Publisher
    ) -> Verifier:
        return Verifier(
            gateway=gateway,
            store=PostgresEventStore(factory),
            publisher=publisher,
            keyframes=Keyframes(),
            rules=RulesConfig(),
            options=VerifierOptions(open_after_s=OPEN_AFTER_S, lease_s=LEASE_S),
            clock=lambda: NOW,
        )

    async def test_a_candidate_becomes_a_verified_event_exactly_once(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        publisher = Publisher()
        gate = self.verifier(session_factory, FakeGateway({"event_verify": YES}), publisher)

        assert await gate.run_once() == 1
        assert await gate.run_once() == 0, "it has its decision, nothing is left to judge"
        assert await gate.run_once() == 0

        [event] = publisher.events
        assert event.event_id == str(c.id) and event.verification.status == "verified"
        [stored] = await sql(
            session_factory,
            "SELECT status, published_at FROM events.events WHERE id = :id",
            id=c.id,
        )
        assert stored["status"] == "verified" and stored["published_at"] == NOW

    async def test_a_rejected_candidate_is_kept_with_its_reason_and_not_announced(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        publisher = Publisher()
        no = {"verdict": "no", "confidence": 0.9, "caption": "An empty yard."}
        await self.verifier(
            session_factory, FakeGateway({"event_verify": no}), publisher
        ).run_once()

        assert publisher.events == []
        [stored] = await sql(
            session_factory, "SELECT status, verification, published_at FROM events.events"
        )
        assert stored["status"] == "rejected" and stored["published_at"] is None
        assert stored["verification"]["reason"] == "the model said this is not happening"

    async def test_an_event_that_could_not_be_sent_is_sent_by_the_next_pass_not_lost(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        publisher = Publisher(failing=True)
        gate = self.verifier(session_factory, FakeGateway({"event_verify": YES}), publisher)

        await gate.run_once()
        [stored] = await sql(session_factory, "SELECT status, published_at FROM events.events")
        assert stored["status"] == "verified" and stored["published_at"] is None

        publisher.failing = False  # kafka is back; even a brand new process finds it in the table
        await self.verifier(session_factory, FakeGateway({}), publisher).run_once()
        assert [e.event_id for e in publisher.events] == [str(c.id)]
        [stored] = await sql(session_factory, "SELECT published_at FROM events.events")
        assert stored["published_at"] == NOW

    async def test_a_candidate_held_for_a_missing_model_comes_back_after_its_back_off(
        self, session_factory: async_sessionmaker
    ) -> None:
        c = update()
        await add(session_factory, c)
        publisher = Publisher()
        gateway = FakeGateway({"event_verify": [LLMUnavailableError("down"), YES]})
        gate = self.verifier(session_factory, gateway, publisher)

        await gate.run_once()
        assert publisher.events == []
        [held] = await sql(
            session_factory, "SELECT verify_attempts, verify_not_before FROM events.candidates"
        )
        assert held["verify_attempts"] == 1
        assert held["verify_not_before"] == NOW + timedelta(seconds=5)  # retry_delay_s(1)

        later = Verifier(
            gateway=gateway,
            store=PostgresEventStore(session_factory),
            publisher=publisher,
            keyframes=Keyframes(),
            rules=RulesConfig(),
            clock=lambda: NOW + timedelta(seconds=6),
        )
        assert await later.run_once() == 1
        assert [e.event_id for e in publisher.events] == [str(c.id)]
