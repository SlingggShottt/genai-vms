"""Incident report synthesis on five real evidence bundles (P6-D1).

The fixtures in `tests/fixtures/` are incidents the system produced on 2026-10-04..06 (zero-shot
`qwen2.5vl:3b` evidence, `qwen2.5:3b` / Gemini synthesis): the stored evidence bundle and the report
built from it. The model's two drafts are rebuilt from that stored report and replayed through
`FakeGateway`, so the tests run the real prompts, validation, citation checks and report assembly
with an answer a model really gave, without a model. Then the ways a model goes wrong are scripted
on the same bundles: an invented evidence id, an uncited claim, a model that is down.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from reasoning.adapters.store import EventInfo
from reasoning.domain.context import build_context
from reasoning.steps.synthesis import synthesize
from vms_common.contracts.reasoning import EvidenceBundleV1, IncidentReportV1
from vms_common.llm.errors import LLMUnavailableError
from vms_common.llm.testing import FakeGateway

FIXTURES = sorted((Path(__file__).resolve().parents[1] / "fixtures").glob("incident_*.json"))
TZ = ZoneInfo("Asia/Kolkata")


def load(path: Path):
    fx = json.loads(path.read_text())
    bundle = EvidenceBundleV1.model_validate(fx["evidence"])
    start = bundle.window.start + timedelta(seconds=12)
    events = [
        EventInfo(
            id=e.id, camera_id=e.camera_id, event_type=e.event_type, severity=bundle.severity,
            rule_id="r", zone_name=None, start=start, end=start + timedelta(seconds=6),
            status="verified", caption=e.caption, confidence=0.9,
        )
        for e in bundle.events
    ]  # fmt: skip
    ctx = build_context(
        events, group_id=bundle.group_id, pad_before_s=12, pad_after_s=12, max_views=2
    )
    assert ctx is not None
    return fx, bundle, ctx


def drafts(report: dict) -> tuple[dict, dict]:
    """The two JSON answers a model would have given to produce this stored report."""
    su = report["scene_understanding"]
    phases = {
        "location": su["location"],
        "conditions": su["conditions"],
        "actors": su["actors"],
        "phases": [
            {"phase": p["phase"], "summary": p["summary"], "evidence": p["evidence"]}
            for p in report["phase_analysis"]
        ],
    }
    cf = report["contributing_factors"]
    causal = {
        "title": report["title"],
        "summary": report["summary"],
        "causal_chain": [
            {"description": s["description"], "evidence": s["evidence"]}
            for s in report["causal_chain"]
        ],
        "primary": cf["primary"],
        "environmental": cf["environmental"],
        "security_gaps": cf["security_gaps"],
        "recommended_actions": report["recommended_actions"],
        "confidence": report["confidence"],
        "limitations": [x for x in report["limitations"] if "left out" not in x],
    }
    return phases, causal


async def run(gateway, ctx, bundle, *, retries: int = 2):
    return await synthesize(
        gateway, ctx, bundle, incident_id="inc-1", tz=TZ, retries=retries, profile="local",
        when="4 Oct 12:01 IST",
    )  # fmt: skip


def ids(path: Path) -> str:
    return path.stem.removeprefix("incident_")


@pytest.mark.parametrize("path", FIXTURES, ids=ids)
async def test_a_recorded_answer_gives_a_valid_report_with_real_citations(path: Path) -> None:
    fx, bundle, ctx = load(path)
    phases, causal = drafts(fx["report"])
    gateway = FakeGateway({"incident_synthesis": [phases, causal]})

    result = await run(gateway, ctx, bundle)

    assert result.error is None and result.report is not None
    assert result.calls == 2 and result.dropped == 0
    report = IncidentReportV1.model_validate(result.report.model_dump())  # schema-valid
    known = bundle.evidence_ids()
    assert report.cited_ids() <= known  # every cited id exists in the bundle
    assert set(report.evidence_index) == report.cited_ids()
    assert report.causal_chain and all(s.evidence for s in report.causal_chain)
    for group in (
        report.contributing_factors.primary,
        report.contributing_factors.environmental,
        report.contributing_factors.security_gaps,
    ):
        assert all(f.evidence for f in group)
    assert {p.phase for p in report.phase_analysis} <= {p.phase for p in bundle.phases}
    assert report.event_type == bundle.event_type and report.cameras == bundle.cameras
    # the stored report is what this answer produced the first time
    assert [s.description for s in report.causal_chain] == [
        s["description"] for s in fx["report"]["causal_chain"]
    ]


async def test_an_invented_evidence_id_is_quoted_back_and_the_corrected_answer_is_used() -> None:
    fx, bundle, ctx = load(FIXTURES[1])
    phases, causal = drafts(fx["report"])
    bad = json.loads(json.dumps(phases))
    bad["phases"][0]["evidence"] = ["ev-cap-99"]
    gateway = FakeGateway({"incident_synthesis": [bad, phases, causal]})

    result = await run(gateway, ctx, bundle)

    assert result.report is not None and result.calls == 3 and result.dropped == 0
    retry = gateway.calls_for("incident_synthesis")[1]
    asked = " ".join(m.content or "" for m in retry.messages if m.role == "user")
    assert "ev-cap-99" in asked and "do not exist" in asked  # the problem was named to the model
    assert "ev-cap-99" not in result.report.cited_ids()


async def test_a_near_miss_id_is_repaired_without_another_call() -> None:
    fx, bundle, ctx = load(FIXTURES[1])
    phases, causal = drafts(fx["report"])
    first = causal["causal_chain"][0]["evidence"][0]  # e.g. "ev-cap-01"
    kind, name, n = first.split("-")
    causal["causal_chain"][0]["evidence"] = [f"[{kind}-{name}-{int(n)}]"]  # "[ev-cap-1]"
    gateway = FakeGateway({"incident_synthesis": [phases, causal]})

    result = await run(gateway, ctx, bundle)

    assert result.calls == 2 and result.report is not None
    assert first in result.report.causal_chain[0].evidence


async def test_a_claim_that_cites_nothing_is_dropped_and_the_report_says_so() -> None:
    fx, bundle, ctx = load(FIXTURES[1])
    phases, causal = drafts(fx["report"])
    causal["causal_chain"].append({"description": "Probably a planned test.", "evidence": []})
    # still wrong after every retry: three identical answers, then it is dropped, never patched
    gateway = FakeGateway({"incident_synthesis": [phases, causal, causal, causal]})

    result = await run(gateway, ctx, bundle)

    assert result.report is not None and result.dropped == 1
    assert result.calls == 4  # the stages once, the causal step three times: it was asked to fix it
    assert "Probably a planned test." not in [s.description for s in result.report.causal_chain]
    assert any("left out" in x for x in result.report.limitations)
    assert result.report.provenance["dropped_claims"] == 1


async def test_a_draft_that_cites_nothing_valid_at_all_is_a_failure_with_the_raw_kept() -> None:
    fx, bundle, ctx = load(FIXTURES[1])
    phases, causal = drafts(fx["report"])
    for p in phases["phases"]:
        p["evidence"] = ["nope"]
    for s in causal["causal_chain"]:
        s["evidence"] = ["nope"]
    for g in ("primary", "environmental", "security_gaps"):
        for f in causal[g]:
            f["evidence"] = ["nope"]
    gateway = FakeGateway({"incident_synthesis": [phases] * 3 + [causal] * 3})

    result = await run(gateway, ctx, bundle)

    assert result.report is None
    assert result.error == "no statement in the draft cited valid evidence"
    assert "nope" in result.raw


@pytest.mark.parametrize("when_down", ["first", "second"])
async def test_a_model_that_is_down_fails_the_report_with_a_reason_instead_of_hanging(
    when_down: str,
) -> None:
    fx, bundle, ctx = load(FIXTURES[1])
    phases, causal = drafts(fx["report"])
    down = LLMUnavailableError("ollama is not running")
    script = [down] if when_down == "first" else [phases, down]
    gateway = FakeGateway({"incident_synthesis": script})

    result = await run(gateway, ctx, bundle)

    assert result.report is None and result.dropped == 0
    assert "ollama is not running" in (result.error or "")
