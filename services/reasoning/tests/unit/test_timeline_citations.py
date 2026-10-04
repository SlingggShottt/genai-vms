from datetime import UTC, datetime, timedelta

from reasoning.domain.citations import problems, prune
from reasoning.domain.sampling import pick_evenly
from reasoning.domain.timeline import rule_spans, spans_from_labels
from reasoning.steps.synthesis import canon_phase
from vms_common.contracts.reasoning import (
    CausalStep,
    ContributingFactors,
    Factor,
    IncidentReportV1,
    SceneUnderstanding,
    Window,
)

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def at(s):
    return T0 + timedelta(seconds=s)


def test_labels_become_contiguous_ordered_spans_and_never_run_backwards():
    spans = spans_from_labels(
        ["baseline", "action", "precursor", "aftermath"],  # 3rd goes backwards -> lifted
        [at(2), at(6), at(10), at(14)],
        window_start=T0,
        window_end=at(16),
        source="t",
    )
    assert [s.phase for s in spans] == ["baseline", "action", "aftermath"]
    assert spans[0].start == T0 and spans[-1].end == at(16)
    assert all(a.end == b.start for a, b in zip(spans, spans[1:], strict=False))


def test_unusable_labels_are_rejected():
    times = [at(2), at(6), at(10)]
    kw = {"window_start": T0, "window_end": at(12), "source": "t"}
    assert spans_from_labels(["action"] * 3, times, **kw) is None  # no boundary information
    assert spans_from_labels(["baseline", "action"], times, **kw) is None  # wrong length


def test_rule_spans_follow_the_detector_and_drop_empty_phases():
    spans = rule_spans(window_start=at(0), window_end=at(40), event_start=at(20), event_end=at(25))
    assert [s.phase for s in spans] == [
        "baseline",
        "precursor",
        "escalation",
        "action",
        "aftermath",
    ]
    action = next(s for s in spans if s.phase == "action")
    assert (action.start, action.end) == (at(20), at(25))
    # an event at the very start of the recording has no lead-in
    early = rule_spans(window_start=at(0), window_end=at(10), event_start=at(0), event_end=at(2))
    assert [s.phase for s in early] == ["action", "aftermath"]


def test_decorated_phase_labels_resolve_to_the_stage():
    assert canon_phase("Stage action (12:01:45–12:01:46)") == "action"
    assert canon_phase("Aftermath phase") == "aftermath"
    assert canon_phase("the end") is None


def _report(step_evidence, factor_evidence):
    return IncidentReportV1(
        incident_id="i",
        title="t",
        summary="s",
        event_type="intrusion",
        severity="high",
        window=Window(start=T0, end=at(10)),
        cameras=["cam01"],
        scene_understanding=SceneUnderstanding(location="l", conditions="c"),
        phase_analysis=[],
        causal_chain=[CausalStep(step=1, description="d", evidence=step_evidence)],
        contributing_factors=ContributingFactors(
            primary=[Factor(text="f", evidence=factor_evidence)]
        ),
        recommended_actions=[],
        confidence=0.5,
    )


def test_every_claim_must_cite_existing_evidence_and_uncited_claims_are_dropped_not_patched():
    known = {"ev-cap-01", "ev-fr-01"}
    assert problems(_report(["ev-cap-01"], ["ev-fr-01"]), known) == []
    bad = _report(["ev-nope"], [])
    assert len(problems(bad, known)) == 3  # unknown id, no valid citation, factor cites nothing
    pruned, dropped = prune(bad, known)
    assert dropped == 2 and pruned.causal_chain == [] and pruned.contributing_factors.primary == []


def test_pick_evenly_keeps_first_and_last():
    picked = pick_evenly(list(range(10)), 4)
    assert picked[0] == 0 and picked[-1] == 9 and len(picked) == 4
    assert pick_evenly([1, 2], 5) == [1, 2]
