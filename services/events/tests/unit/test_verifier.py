"""The VLM verification gate end to end, with a fake gateway, store, publisher and keyframes
(P3-D4). Nothing here touches the network, Postgres, Kafka or a real model."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from events.domain.config import RulesConfig
from events.domain.evidence import EvidenceBox, EvidenceFrame
from events.domain.records import EventRow, PendingCandidate
from events.domain.rules import registered_rules
from events.domain.verification import GatePolicy, Verdict, retry_delay_s
from events.verifier import Verifier, VerifierOptions
from PIL import Image
from prometheus_client import REGISTRY
from vms_common.contracts.event import EventV1
from vms_common.llm import LLMOutputError, LLMUnavailableError
from vms_common.llm.testing import FakeGateway
from vms_common.llm.types import ChatResult

NOW = datetime(2026, 10, 1, 7, 5, tzinfo=UTC)
START = NOW - timedelta(seconds=60)
YES = {"verdict": "yes", "confidence": 0.9, "caption": "A person climbs the gate."}
NO = {"verdict": "no", "confidence": 0.8, "caption": "An empty yard."}
UNSURE = {"verdict": "unsure", "confidence": 0.3, "caption": "Too dark to tell."}


def jpeg() -> bytes:
    out = BytesIO()
    Image.new("RGB", (448, 252), (0, 0, 255)).save(out, format="JPEG", quality=95)
    return out.getvalue()


def uri(n: int) -> str:
    return f"s3://vms-keyframes/cam01/{n:04d}.jpg"


def frame(n: int, *, track: str = "cam01-t1") -> EvidenceFrame:
    return EvidenceFrame(
        ts=START + timedelta(seconds=5 * n),
        segment_id=f"cam01_seg_{n // 2}",
        keyframe_uri=uri(n),
        boxes=[EvidenceBox(track_id=track, category="person", bbox=(0.25, 0.25, 0.75, 0.75))],
    )


def candidate(
    *,
    severity: str = "high",
    rule_id: str = "intrusion.restricted",
    event_type: str = "intrusion",
    frames: int = 6,
    attempts: int = 1,
    first_at: datetime = NOW,
    zone_name: str | None = "Gate",
    **overrides: Any,
) -> PendingCandidate:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "site_id": "rvce-campus",
        "camera_id": "cam01",
        "rule_id": rule_id,
        "event_type": event_type,
        "severity": severity,
        "zone_id": "zone-gate" if zone_name else None,
        "zone_name": zone_name,
        "track_ids": ["cam01-t1"],
        "segment_ids": ["cam01_seg_0", "cam01_seg_1"],
        "start_ts": START,
        "end_ts": NOW - timedelta(seconds=10),
        "rule_score": 0.91,
        "status": "closed",
        "details": {"evidence": [frame(n).model_dump(mode="json") for n in range(frames)]},
        "attempts": attempts,
        "first_at": first_at,
    }
    return PendingCandidate(**(base | overrides))


@dataclass
class FakeStore:
    queue: list[PendingCandidate] = field(default_factory=list)
    rows: dict[uuid.UUID, EventRow] = field(default_factory=dict)
    published: dict[uuid.UUID, datetime] = field(default_factory=dict)
    rescheduled: list[tuple[uuid.UUID, datetime]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    claim_error: Exception | None = None
    claim_limit: int | None = None  # a loop that never sleeps hits this instead of hanging the run

    async def claim(self, **kwargs: Any) -> list[PendingCandidate]:
        self.claims.append(kwargs)
        if self.claim_limit is not None and len(self.claims) > self.claim_limit:
            raise asyncio.CancelledError
        if self.claim_error is not None:
            raise self.claim_error
        batch, self.queue = self.queue[: kwargs["limit"]], self.queue[kwargs["limit"] :]
        return batch

    async def save_event(self, row: EventRow) -> bool:
        if row.id in self.rows:
            return False
        self.rows[row.id] = row
        return True

    async def reschedule(self, candidate_id: uuid.UUID, not_before: datetime) -> None:
        self.rescheduled.append((candidate_id, not_before))

    async def unpublished(self, *, limit: int) -> list[EventRow]:
        waiting = [
            r for r in self.rows.values() if r.status != "rejected" and r.id not in self.published
        ]
        return waiting[:limit]

    async def mark_published(self, event_id: uuid.UUID, at: datetime) -> None:
        self.published[event_id] = at


@dataclass
class FakePublisher:
    store: FakeStore
    events: list[EventV1] = field(default_factory=list)
    saved_when_sent: list[bool] = field(default_factory=list)
    failing: bool = False
    tries: int = 0

    async def publish(self, event: EventV1) -> None:
        self.tries += 1
        if self.failing:
            raise ConnectionError("kafka is down")
        self.saved_when_sent.append(uuid.UUID(event.event_id) in self.store.rows)
        self.events.append(event)


@dataclass
class FakeKeyframes:
    missing: set[str] = field(default_factory=set)
    not_images: set[str] = field(default_factory=set)
    asked: list[list[str]] = field(default_factory=list)

    async def load(self, frames: list[EvidenceFrame]) -> list[tuple[EvidenceFrame, bytes]]:
        self.asked.append([f.keyframe_uri for f in frames])
        return [
            (f, b"this is not a jpeg" if f.keyframe_uri in self.not_images else jpeg())
            for f in frames
            if f.keyframe_uri not in self.missing
        ]


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def build() -> Callable[..., SimpleNamespace]:
    def factory(
        gateway: FakeGateway | None = None,
        *,
        candidates: list[PendingCandidate] | None = None,
        rules: RulesConfig | None = None,
        policy: GatePolicy | None = None,
        options: VerifierOptions | None = None,
        sleep: Callable[[float], Any] | None = None,
    ) -> SimpleNamespace:
        store = FakeStore(queue=list(candidates or []))
        publisher = FakePublisher(store)
        keyframes = FakeKeyframes()
        gateway = gateway or FakeGateway({"event_verify": YES})
        kwargs: dict[str, Any] = {}
        if sleep is not None:
            kwargs["sleep"] = sleep
        verifier = Verifier(
            gateway=gateway,
            store=store,
            publisher=publisher,
            keyframes=keyframes,
            rules=rules or RulesConfig(),
            policy=policy,
            options=options,
            clock=lambda: NOW,
            **kwargs,
        )
        return SimpleNamespace(
            verifier=verifier,
            store=store,
            publisher=publisher,
            keyframes=keyframes,
            gateway=gateway,
        )

    return factory


def one(world: SimpleNamespace) -> EventRow:
    assert len(world.store.rows) == 1
    return next(iter(world.store.rows.values()))


def result(verdict: dict[str, Any], *, latency_s: float = 5.21) -> Callable[..., ChatResult]:
    parsed = Verdict.model_validate(verdict)
    return lambda call: ChatResult(
        task="event_verify",
        provider="ollama",
        model="qwen2.5vl:3b",
        text=parsed.model_dump_json(),
        parsed=parsed,
        latency_s=latency_s,
    )


class TestAConfirmedEvent:
    async def test_is_saved_as_verified_and_published_as_event_v1(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        c = candidate()
        world = build(FakeGateway({"event_verify": result(YES)}), candidates=[c])
        sent_before = sample("vms_events_published_total", status="verified")
        model_time_before = sample("vms_events_verification_seconds_sum")

        assert await world.verifier.run_once() == 1

        assert sample("vms_events_published_total", status="verified") == sent_before + 1
        assert sample("vms_events_verification_seconds_sum") == pytest.approx(
            model_time_before + 5.21
        )
        row = one(world)
        assert (row.id, row.status) == (c.id, "verified")
        [event] = world.publisher.events
        assert event.schema_version == "event.v1"
        assert event.event_id == str(c.id)
        assert (event.site_id, event.camera_id, event.event_type) == (
            "rvce-campus",
            "cam01",
            "intrusion",
        )
        assert (event.severity, event.rule_id, event.rule_score) == (
            "high",
            "intrusion.restricted",
            0.91,
        )
        assert (event.zone_id, event.track_ids) == ("zone-gate", ["cam01-t1"])
        assert event.segment_ids == c.segment_ids
        assert (event.start_ts, event.end_ts) == (c.start_ts, c.end_ts)
        assert event.verification.model_dump() == {
            "status": "verified",
            "confidence": 0.9,
            "caption": "A person climbs the gate.",
            "model": "ollama/qwen2.5vl:3b",
            "latency_ms": 5210,
        }
        assert world.store.published == {c.id: NOW}

    async def test_the_decision_is_saved_before_it_is_sent(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate()])
        await world.verifier.run_once()
        assert world.publisher.saved_when_sent == [True]

    async def test_the_row_keeps_what_the_model_said_and_why(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(
            FakeGateway({"event_verify": result(YES)}), candidates=[candidate(attempts=2)]
        )
        await world.verifier.run_once()

        record = one(world).verification
        assert record["status"] == "verified" and record["reason"] == "the model confirmed it"
        assert (record["verdict"], record["confidence"], record["flagged"]) == ("yes", 0.9, False)
        assert (record["model"], record["latency_ms"], record["frames"]) == (
            "ollama/qwen2.5vl:3b",
            5210,
            4,
        )
        assert (record["attempts"], record["prompt_version"]) == (2, "1.0")

    async def test_the_event_names_the_frames_the_model_saw(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate(frames=10)])
        await world.verifier.run_once()

        shown = world.publisher.events[0].keyframe_uris
        assert len(shown) == 4
        assert shown[0] == uri(0) and shown[-1] == uri(9), "the first and the latest frame"
        assert world.keyframes.asked == [shown]


class TestWhatTheModelIsAsked:
    async def test_up_to_four_frames_with_the_flagged_boxes_drawn_on_them(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate(frames=10)])
        await world.verifier.run_once()

        [call] = world.gateway.calls_for("event_verify")
        assert len(call.images) == 4 and call.response_model is Verdict
        picture = Image.open(BytesIO(call.images[0].data)).convert("RGB")
        r, g, b = picture.getpixel((112, 126))  # the left edge of the box (0.25 * 448)
        assert r > 200 and g < 90 and b < 90, "the box is drawn"
        assert picture.getpixel((224, 126))[2] > 200, "and the inside is left alone"

    async def test_the_prompt_states_the_claim_the_place_and_when_the_frames_are_from(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate(frames=3)])
        await world.verifier.run_once()

        prompt = world.gateway.calls_for("event_verify")[0].prompt
        assert registered_rules()["intrusion.restricted"].description in prompt
        assert "Camera: cam01; area: Gate" in prompt
        assert "Frames: 3 from this camera" in prompt
        assert "frame 1 at +0 s, frame 2 at +5 s, frame 3 at +10 s" in prompt

    async def test_a_camera_wide_candidate_has_no_area(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(
            candidates=[
                candidate(rule_id="running", event_type="running", severity="low", zone_name=None)
            ]
        )
        await world.verifier.run_once()
        prompt = world.gateway.calls_for("event_verify")[0].prompt
        assert "Camera: cam01\n" in prompt and "area:" not in prompt
        assert "A person is running." in prompt

    @pytest.mark.parametrize("rule_id", sorted(registered_rules()))
    async def test_every_rule_is_judged_against_its_own_claim(
        self, build: Callable[..., SimpleNamespace], rule_id: str
    ) -> None:
        rule = registered_rules()[rule_id]
        world = build(candidates=[candidate(rule_id=rule_id, event_type=rule.event_type)])
        await world.verifier.run_once()
        assert rule.description in world.gateway.calls_for("event_verify")[0].prompt

    async def test_a_rule_that_is_no_longer_registered_still_gets_a_claim_from_its_type(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate(rule_id="retired.rule", event_type="abandoned_object")])
        await world.verifier.run_once()
        assert 'An event of type "abandoned object" is happening.' in (
            world.gateway.calls_for("event_verify")[0].prompt
        )


class TestWhatTheGateDecides:
    async def test_a_no_is_stored_with_its_reason_and_never_published(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        before = sample(
            "vms_events_verifications_total", rule="intrusion.restricted", outcome="rejected"
        )
        world = build(FakeGateway({"event_verify": NO}), candidates=[candidate()])
        await world.verifier.run_once()

        row = one(world)
        assert row.status == "rejected"
        assert row.verification["reason"] == "the model said this is not happening"
        assert row.verification["caption"] == "An empty yard."
        assert world.publisher.events == [] and world.store.published == {}
        assert (
            sample(
                "vms_events_verifications_total", rule="intrusion.restricted", outcome="rejected"
            )
            == before + 1
        )

    async def test_unsure_for_a_low_severity_rule_is_published_flagged(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(
            FakeGateway({"event_verify": UNSURE}),
            candidates=[candidate(rule_id="running", event_type="running", severity="low")],
        )
        await world.verifier.run_once()

        assert one(world).status == "verified" and one(world).verification["flagged"] is True
        assert world.publisher.events[0].verification.confidence == 0.3

    async def test_unsure_for_a_high_severity_rule_is_rejected(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(FakeGateway({"event_verify": UNSURE}), candidates=[candidate()])
        await world.verifier.run_once()
        assert one(world).status == "rejected" and world.publisher.events == []

    async def test_a_yes_the_model_is_not_sure_of_is_not_trusted(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        weak = {"verdict": "yes", "confidence": 0.4, "caption": "Maybe a person."}
        world = build(FakeGateway({"event_verify": weak}), candidates=[candidate()])
        await world.verifier.run_once()
        assert one(world).status == "rejected"
        assert "0.40" in one(world).verification["reason"]

    async def test_the_policy_is_the_one_it_was_given(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(
            FakeGateway({"event_verify": UNSURE}),
            candidates=[candidate()],
            policy=GatePolicy(unsure_accepted_up_to="high"),
        )
        await world.verifier.run_once()
        assert one(world).status == "verified"


class TestARuleThatDoesNotNeedTheGate:
    def config(self) -> RulesConfig:
        return RulesConfig.model_validate({"rules": {"loitering": {"verify": False}}})

    async def test_is_published_as_skipped_without_asking_the_model(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(
            FakeGateway({}),
            candidates=[candidate(rule_id="loitering", event_type="loitering", severity="medium")],
            rules=self.config(),
        )
        await world.verifier.run_once()

        row = one(world)
        assert row.status == "skipped"
        assert row.verification["reason"] == "verification is turned off for this rule"
        assert world.gateway.calls == []
        [event] = world.publisher.events
        assert event.verification.status == "skipped"
        assert event.verification.confidence is None and event.verification.model is None

    async def test_a_camera_override_can_turn_it_off_for_one_camera_only(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        rules = RulesConfig.model_validate(
            {"overrides": [{"rule": "intrusion.restricted", "camera": "cam07", "verify": False}]}
        )
        world = build(
            candidates=[candidate(camera_id="cam07"), candidate(camera_id="cam01")], rules=rules
        )
        await world.verifier.run_once()

        by_camera = {r.camera_id: r.status for r in world.store.rows.values()}
        assert by_camera == {"cam07": "skipped", "cam01": "verified"}
        assert len(world.gateway.calls) == 1


class TestWhenThereIsNoModelToAsk:
    def down(self) -> FakeGateway:
        return FakeGateway({"event_verify": LLMUnavailableError("ollama is not running")})

    async def test_a_high_severity_candidate_waits_and_is_retried_with_back_off(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        before = sample(
            "vms_events_verifications_total", rule="intrusion.restricted", outcome="held"
        )
        c = candidate(severity="high", attempts=3, first_at=NOW - timedelta(seconds=60))
        world = build(self.down(), candidates=[c])
        await world.verifier.run_once()

        assert world.store.rows == {} and world.publisher.events == []
        assert world.store.rescheduled == [
            (c.id, NOW + timedelta(seconds=retry_delay_s(3)))
        ]  # 5 * 2**2 = 20 s
        assert (
            sample("vms_events_verifications_total", rule="intrusion.restricted", outcome="held")
            == before + 1
        )

    async def test_a_medium_one_waits_too_because_it_raises_an_alert(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(self.down(), candidates=[candidate(severity="medium")])
        await world.verifier.run_once()
        assert world.store.rows == {} and len(world.store.rescheduled) == 1

    async def test_a_low_severity_one_is_published_unverified_at_once(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(
            self.down(),
            candidates=[candidate(rule_id="running", event_type="running", severity="low")],
        )
        await world.verifier.run_once()

        row = one(world)
        assert row.status == "skipped"
        assert row.verification["reason"] == (
            "the model could not be reached (ollama is not running); "
            "published unverified (low severity)"
        )
        assert world.publisher.events[0].verification.status == "skipped"
        assert world.store.rescheduled == []

    async def test_after_waiting_as_long_as_it_may_a_held_one_is_published_unverified(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        c = candidate(severity="high", attempts=9, first_at=NOW - timedelta(seconds=601))
        world = build(self.down(), candidates=[c], policy=GatePolicy(hold_max_age_s=600))
        await world.verifier.run_once()

        row = one(world)
        assert row.status == "skipped" and world.store.rescheduled == []
        assert row.verification["reason"] == (
            "the model could not be reached (ollama is not running); "
            "published unverified after waiting 601 s (high severity)"
        )
        assert len(world.publisher.events) == 1

    async def test_just_inside_the_limit_it_still_waits(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        c = candidate(severity="high", first_at=NOW - timedelta(seconds=599))
        world = build(self.down(), candidates=[c], policy=GatePolicy(hold_max_age_s=600))
        await world.verifier.run_once()
        assert world.store.rows == {} and len(world.store.rescheduled) == 1

    async def test_a_timeout_is_the_same_as_being_down(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        from vms_common.llm import LLMTimeoutError

        world = build(
            FakeGateway({"event_verify": LLMTimeoutError("no answer in 60 s")}),
            candidates=[candidate()],
        )
        await world.verifier.run_once()
        assert world.store.rows == {} and len(world.store.rescheduled) == 1

    async def test_once_the_model_is_back_the_held_candidate_is_judged_normally(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        c = candidate()
        gateway = FakeGateway({"event_verify": [LLMUnavailableError("down"), YES]})
        world = build(gateway, candidates=[c])
        await world.verifier.run_once()
        assert world.store.rows == {}

        world.store.queue = [c]  # the store offers it again once its back-off has passed
        await world.verifier.run_once()
        assert one(world).status == "verified" and len(world.publisher.events) == 1


class TestAnAnswerThatCannotBeRead:
    def garbled(self) -> FakeGateway:
        return FakeGateway({"event_verify": LLMOutputError("never valid", last_text="I think so")})

    async def test_counts_as_unsure_and_the_usual_policy_applies(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        high = build(self.garbled(), candidates=[candidate(severity="high")])
        await high.verifier.run_once()
        assert one(high).status == "rejected"
        assert one(high).verification["reason"] == (
            "the model's answer could not be read, counted as unsure; "
            "the model was unsure; not accepted for a high-severity rule"
        )

        low = build(
            self.garbled(),
            candidates=[candidate(rule_id="running", event_type="running", severity="low")],
        )
        await low.verifier.run_once()
        assert one(low).status == "verified" and one(low).verification["flagged"] is True
        assert one(low).verification["confidence"] == 0.0


class TestKeyframesThatCannotBeRead:
    async def test_the_model_is_asked_about_the_frames_that_could_be_read(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate(frames=4)])
        world.keyframes.missing = {uri(1)}
        await world.verifier.run_once()

        assert len(world.gateway.calls_for("event_verify")[0].images) == 3
        assert uri(1) not in one(world).keyframe_uris and one(world).verification["frames"] == 3

    async def test_a_file_that_is_not_an_image_is_left_out_not_fatal(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate(frames=4)])
        world.keyframes.not_images = {uri(2)}
        await world.verifier.run_once()

        assert len(world.gateway.calls_for("event_verify")[0].images) == 3
        assert one(world).status == "verified"

    async def test_with_none_left_it_is_the_same_as_no_model(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate(frames=3)])
        world.keyframes.missing = {uri(0), uri(1), uri(2)}
        await world.verifier.run_once()

        assert world.gateway.calls == [] and world.store.rows == {}
        assert len(world.store.rescheduled) == 1

        low = build(
            candidates=[
                candidate(rule_id="running", event_type="running", severity="low", frames=3)
            ]
        )
        low.keyframes.missing = {uri(0), uri(1), uri(2)}
        await low.verifier.run_once()
        assert "its keyframes could not be read" in one(low).verification["reason"]
        assert one(low).status == "skipped"

    async def test_a_candidate_that_recorded_no_keyframes_is_published_skipped(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate(details={})])
        await world.verifier.run_once()

        row = one(world)
        assert row.status == "skipped" and row.keyframe_uris == []
        assert row.verification["reason"] == "the candidate recorded no keyframes"
        assert world.gateway.calls == []

    async def test_an_evidence_entry_that_does_not_parse_is_not_evidence(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        details = {"evidence": [{"nonsense": True}, frame(0).model_dump(mode="json")]}
        world = build(candidates=[candidate(details=details)])
        await world.verifier.run_once()
        assert len(world.gateway.calls_for("event_verify")[0].images) == 1


class TestWhenSomethingUnexpectedGoesWrong:
    async def test_the_candidate_is_kept_for_later_and_the_others_are_still_judged(
        self, build: Callable[..., SimpleNamespace], caplog: pytest.LogCaptureFixture
    ) -> None:
        bad, good = candidate(attempts=2), candidate()
        before = sample("vms_events_verification_errors_total", rule="intrusion.restricted")
        gateway = FakeGateway({"event_verify": [RuntimeError("a bug"), YES]})
        world = build(gateway, candidates=[bad, good])

        assert await world.verifier.run_once() == 2

        assert world.store.rescheduled == [(bad.id, NOW + timedelta(seconds=retry_delay_s(2)))]
        assert list(world.store.rows) == [good.id]
        assert (
            sample("vms_events_verification_errors_total", rule="intrusion.restricted")
            == before + 1
        )

    async def test_a_request_the_gateway_calls_wrong_is_surfaced_not_swallowed(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        from vms_common.llm import LLMRequestError

        c = candidate()
        world = build(
            FakeGateway({"event_verify": LLMRequestError("5 images exceed the cap")}),
            candidates=[c],
        )
        await world.verifier.run_once()
        assert world.store.rows == {} and [r[0] for r in world.store.rescheduled] == [c.id]


class TestPublishing:
    async def test_a_send_that_fails_leaves_the_event_to_be_sent_by_the_next_pass(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        c = candidate()
        world = build(candidates=[c])
        world.publisher.failing = True
        await world.verifier.run_once()

        assert one(world).status == "verified" and world.store.published == {}

        sent_before = sample("vms_events_published_total", status="verified")
        world.publisher.failing = False
        await world.verifier.run_once()
        assert [e.event_id for e in world.publisher.events] == [str(c.id)]
        assert world.store.published == {c.id: NOW}
        assert sample("vms_events_published_total", status="verified") == sent_before + 1

    async def test_what_is_already_sent_is_not_sent_again(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(candidates=[candidate()])
        await world.verifier.run_once()
        await world.verifier.run_once()
        await world.verifier.run_once()
        assert len(world.publisher.events) == 1

    async def test_a_rejected_event_is_never_in_the_outbox(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(FakeGateway({"event_verify": NO}), candidates=[candidate()])
        await world.verifier.run_once()
        assert await world.verifier.publish_pending() == 0

    async def test_stops_at_the_first_failure_rather_than_hammering_a_dead_broker(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build()
        for _ in range(3):
            c = candidate()
            world.store.rows[c.id] = EventRow(
                id=c.id,
                site_id=c.site_id,
                camera_id=c.camera_id,
                event_type=c.event_type,
                severity=c.severity,
                rule_id=c.rule_id,
                rule_score=c.rule_score,
                zone_id=c.zone_id,
                zone_name=c.zone_name,
                track_ids=c.track_ids,
                segment_ids=c.segment_ids,
                keyframe_uris=[uri(0)],
                start_ts=c.start_ts,
                end_ts=c.end_ts,
                status="verified",
                verification={"status": "verified", "confidence": 0.9},
            )
        world.publisher.failing = True
        assert await world.verifier.publish_pending() == 0
        assert world.publisher.tries == 1, "one try, not one per waiting event"
        world.publisher.failing = False
        assert await world.verifier.publish_pending() == 3

    async def test_a_candidate_someone_else_already_decided_is_not_announced_twice(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        c = candidate()
        world = build(candidates=[c])
        other = EventRow(
            id=c.id,
            site_id=c.site_id,
            camera_id=c.camera_id,
            event_type=c.event_type,
            severity=c.severity,
            rule_id=c.rule_id,
            rule_score=c.rule_score,
            zone_id=None,
            zone_name=None,
            track_ids=[],
            segment_ids=[],
            keyframe_uris=[],
            start_ts=c.start_ts,
            end_ts=c.end_ts,
            status="rejected",
            verification={"status": "rejected"},
        )
        world.store.rows[c.id] = other

        await world.verifier.run_once()
        assert world.store.rows[c.id] is other and world.publisher.events == []


class TestTheLoop:
    async def test_asks_the_store_with_its_options(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        options = VerifierOptions(
            batch_size=2, lease_s=111, open_after_s=22, max_age_s=3333, poll_s=1
        )
        world = build(options=options)
        assert await world.verifier.run_once() == 0
        assert world.store.claims == [
            {"now": NOW, "limit": 2, "lease_s": 111, "open_after_s": 22, "max_age_s": 3333}
        ]

    async def test_a_batch_is_no_bigger_than_asked(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        world = build(
            candidates=[candidate() for _ in range(5)], options=VerifierOptions(batch_size=2)
        )
        assert await world.verifier.run_once() == 2 and len(world.store.rows) == 2
        assert await world.verifier.run_once() == 2 and len(world.store.rows) == 4

    async def test_run_sleeps_when_idle_and_goes_straight_on_when_busy(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        slept: list[float] = []

        async def sleep(seconds: float) -> None:
            slept.append(seconds)
            if len(slept) == 2:
                raise asyncio.CancelledError

        world = build(candidates=[candidate()], options=VerifierOptions(poll_s=7), sleep=sleep)
        world.store.claim_limit = 20
        with pytest.raises(asyncio.CancelledError):
            await world.verifier.run()

        # pass 1 judged a candidate (no sleep), passes 2 and 3 found nothing (slept 7 s each)
        assert slept == [7, 7] and len(world.store.rows) == 1

    async def test_a_failing_pass_is_logged_and_the_loop_carries_on(
        self, build: Callable[..., SimpleNamespace]
    ) -> None:
        slept: list[float] = []

        async def sleep(seconds: float) -> None:
            slept.append(seconds)
            if len(slept) == 2:
                raise asyncio.CancelledError

        world = build(sleep=sleep)
        world.store.claim_limit = 20
        world.store.claim_error = ConnectionError("postgres is restarting")
        with pytest.raises(asyncio.CancelledError):
            await world.verifier.run()
        assert len(slept) == 2 and len(world.store.claims) == 2

    async def test_cancelling_it_stops_it(self, build: Callable[..., SimpleNamespace]) -> None:
        world = build(options=VerifierOptions(poll_s=0.01))
        task = asyncio.create_task(world.verifier.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
