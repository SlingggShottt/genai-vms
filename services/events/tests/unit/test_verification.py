"""The VLM gate's decisions (design §7.4, P3-D4) — pure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from events.domain.evidence import EvidenceFrame
from events.domain.verification import (
    GatePolicy,
    Verdict,
    decide,
    offsets_s,
    retry_delay_s,
    select_frames,
    unavailable_action,
    verification_record,
)
from pydantic import ValidationError

T0 = datetime(2026, 10, 1, 7, 0, 0, tzinfo=UTC)
POLICY = GatePolicy()


def verdict(value: str = "yes", confidence: float = 0.9, caption: str = "A person.") -> Verdict:
    return Verdict(verdict=value, confidence=confidence, caption=caption)  # type: ignore[arg-type]


class TestTheVerdictTheModelReturns:
    def test_the_documented_shape_parses(self) -> None:
        parsed = Verdict.model_validate(
            {"verdict": "yes", "confidence": 0.84, "caption": "A person climbs the gate."}
        )
        assert (parsed.verdict, parsed.confidence, parsed.caption) == (
            "yes",
            0.84,
            "A person climbs the gate.",
        )

    @pytest.mark.parametrize("raw", ["Yes", " YES ", "yes\n"])
    def test_case_and_padding_are_tolerated(self, raw: str) -> None:
        assert Verdict.model_validate({"verdict": raw, "confidence": 0.7}).verdict == "yes"

    @pytest.mark.parametrize("raw", ["maybe", "true", "", None, 1])
    def test_a_verdict_that_is_not_yes_no_or_unsure_is_refused(self, raw: object) -> None:
        with pytest.raises(ValidationError):
            Verdict.model_validate({"verdict": raw, "confidence": 0.7})

    @pytest.mark.parametrize("confidence", [-0.01, 1.01, "high", None])
    def test_a_confidence_outside_zero_to_one_is_refused(self, confidence: object) -> None:
        with pytest.raises(ValidationError):
            Verdict.model_validate({"verdict": "yes", "confidence": confidence})

    def test_a_missing_confidence_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            Verdict.model_validate({"verdict": "yes"})

    def test_the_ends_of_the_confidence_range_are_fine(self) -> None:
        assert Verdict.model_validate({"verdict": "no", "confidence": 0}).confidence == 0
        assert Verdict.model_validate({"verdict": "no", "confidence": 1}).confidence == 1

    def test_a_missing_or_null_caption_is_empty_and_a_padded_one_is_trimmed(self) -> None:
        assert Verdict.model_validate({"verdict": "no", "confidence": 0.5}).caption == ""
        assert (
            Verdict.model_validate({"verdict": "no", "confidence": 0.5, "caption": None}).caption
            == ""
        )
        assert verdict(caption="  Two people.  ").caption == "Two people."

    def test_a_caption_that_runs_on_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            verdict(caption="x" * 601)

    def test_extra_keys_models_like_to_add_are_ignored(self) -> None:
        parsed = Verdict.model_validate(
            {"verdict": "yes", "confidence": 0.9, "caption": "x", "reasoning": "because"}
        )
        assert not hasattr(parsed, "reasoning")


class TestWhatTheGateConcludes:
    @pytest.mark.parametrize("severity", ["low", "medium", "high", "critical"])
    def test_a_confident_yes_is_verified_at_any_severity(self, severity: str) -> None:
        decision = decide(verdict("yes", 0.9), severity, POLICY)
        assert (decision.status, decision.flagged) == ("verified", False)

    def test_yes_at_exactly_the_minimum_confidence_is_enough(self) -> None:
        assert decide(verdict("yes", 0.6), "high", POLICY).status == "verified"

    def test_yes_just_below_it_is_not_trusted(self) -> None:
        decision = decide(verdict("yes", 0.59), "high", POLICY)
        assert decision.status == "rejected"
        assert "0.59" in decision.reason and "0.60" in decision.reason

    @pytest.mark.parametrize("severity", ["low", "medium", "high", "critical"])
    @pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
    def test_no_is_always_rejected_however_sure_and_whatever_the_severity(
        self, severity: str, confidence: float
    ) -> None:
        assert decide(verdict("no", confidence), severity, POLICY).status == "rejected"

    def test_unsure_is_accepted_but_flagged_for_a_low_severity_rule(self) -> None:
        decision = decide(verdict("unsure", 0.4), "low", POLICY)
        assert (decision.status, decision.flagged) == ("verified", True)
        assert "unsure" in decision.reason and "low-severity" in decision.reason

    @pytest.mark.parametrize("severity", ["medium", "high", "critical"])
    def test_unsure_is_rejected_above_that(self, severity: str) -> None:
        decision = decide(verdict("unsure", 0.4), severity, POLICY)
        assert (decision.status, decision.flagged) == ("rejected", False)
        assert severity in decision.reason

    def test_a_weak_yes_is_treated_like_unsure(self) -> None:
        weak = verdict("yes", 0.3)
        assert decide(weak, "low", POLICY).flagged is True
        assert decide(weak, "medium", POLICY).status == "rejected"

    def test_what_counts_as_doubtful_enough_to_accept_is_configurable(self) -> None:
        policy = GatePolicy(unsure_accepted_up_to="medium")
        assert decide(verdict("unsure", 0.4), "medium", policy).status == "verified"
        assert decide(verdict("unsure", 0.4), "high", policy).status == "rejected"

    def test_the_minimum_confidence_is_configurable(self) -> None:
        assert (
            decide(verdict("yes", 0.7), "high", GatePolicy(min_confidence=0.8)).status == "rejected"
        )
        assert (
            decide(verdict("yes", 0.7), "high", GatePolicy(min_confidence=0.7)).status == "verified"
        )


class TestWhenNobodyCanBeAsked:
    def test_a_low_severity_candidate_is_published_unverified_at_once(self) -> None:
        assert unavailable_action("low", 0, POLICY) == "skip"

    @pytest.mark.parametrize("severity", ["medium", "high", "critical"])
    def test_anything_that_raises_an_alert_waits(self, severity: str) -> None:
        assert unavailable_action(severity, 0, POLICY) == "hold"

    def test_until_it_has_waited_as_long_as_it_may(self) -> None:
        assert unavailable_action("high", 599.9, POLICY) == "hold"
        assert unavailable_action("high", 600, POLICY) == "skip"
        assert unavailable_action("high", 3600, POLICY) == "skip"

    def test_where_waiting_starts_is_configurable(self) -> None:
        policy = GatePolicy(hold_from="high")
        assert unavailable_action("medium", 0, policy) == "skip"
        assert unavailable_action("high", 0, policy) == "hold"

    def test_a_zero_wait_never_holds(self) -> None:
        assert unavailable_action("critical", 0, GatePolicy(hold_max_age_s=0)) == "skip"


class TestRetryDelay:
    def test_doubles_from_the_base(self) -> None:
        assert [retry_delay_s(n) for n in (1, 2, 3, 4)] == [5, 10, 20, 40]

    def test_is_capped(self) -> None:
        assert retry_delay_s(7) == 300 and retry_delay_s(50) == 300

    def test_before_any_failure_it_is_the_base(self) -> None:
        assert retry_delay_s(0) == 5

    def test_base_and_cap_are_parameters(self) -> None:
        assert retry_delay_s(3, base_s=1, cap_s=3) == 3


class TestFramesSentToTheModel:
    def frames(self, n: int) -> list[EvidenceFrame]:
        return [
            EvidenceFrame(
                ts=T0 + timedelta(seconds=3 * i),
                segment_id="seg",
                keyframe_uri=f"s3://vms-keyframes/cam01/{i:04d}.jpg",
            )
            for i in range(n)
        ]

    def test_at_most_four_in_time_order_spanning_the_candidate(self) -> None:
        picked = select_frames(list(reversed(self.frames(12))))
        assert len(picked) == 4
        assert [f.ts for f in picked] == sorted(f.ts for f in picked)
        assert picked[0].ts == T0 and picked[-1].ts == T0 + timedelta(seconds=33)

    def test_fewer_than_four_are_all_used(self) -> None:
        assert select_frames(self.frames(2)) == self.frames(2)

    def test_none_is_none(self) -> None:
        assert select_frames([]) == []

    def test_offsets_are_seconds_from_the_first_frame(self) -> None:
        assert offsets_s(self.frames(3)) == [0, 3, 6]
        assert offsets_s([]) == []


class TestTheRecordStored:
    def test_a_decision_keeps_what_the_model_said_and_why(self) -> None:
        record = verification_record(
            "verified",
            "the model confirmed it",
            verdict=verdict("yes", 0.84, "A person climbs the gate."),
            model="ollama/qwen2.5vl:3b",
            latency_ms=5210,
            frames=4,
            attempts=1,
            prompt_version="1.0",
        )
        assert record == {
            "status": "verified",
            "reason": "the model confirmed it",
            "verdict": "yes",
            "confidence": 0.84,
            "caption": "A person climbs the gate.",
            "flagged": False,
            "model": "ollama/qwen2.5vl:3b",
            "latency_ms": 5210,
            "frames": 4,
            "attempts": 1,
            "prompt_version": "1.0",
        }

    def test_when_the_model_was_not_asked_what_it_says_is_absent_not_invented(self) -> None:
        record = verification_record("skipped", "verify is off for this rule")
        assert record["verdict"] is None and record["confidence"] is None
        assert (
            record["caption"] is None and record["model"] is None and record["latency_ms"] is None
        )
        assert record["status"] == "skipped" and record["frames"] == 0

    def test_an_empty_caption_is_absent_and_a_flag_is_kept(self) -> None:
        record = verification_record(
            "verified", "unsure, accepted", verdict=verdict("unsure", 0.2, ""), flagged=True
        )
        assert record["caption"] is None and record["flagged"] is True


class TestThePolicyItself:
    @pytest.mark.parametrize("minimum", [0, 0.6, 1])
    def test_a_minimum_confidence_from_zero_to_one_inclusive_is_fine(self, minimum: float) -> None:
        assert GatePolicy(min_confidence=minimum).min_confidence == minimum

    @pytest.mark.parametrize(
        "bad",
        [
            {"min_confidence": -0.1},
            {"min_confidence": 1.1},
            {"hold_max_age_s": -1},
            {"unsure_accepted_up_to": "severe"},
            {"hold_from": "urgent"},
        ],
    )
    def test_nonsense_is_refused_at_construction(self, bad: dict) -> None:
        with pytest.raises(ValueError):
            GatePolicy(**bad)
