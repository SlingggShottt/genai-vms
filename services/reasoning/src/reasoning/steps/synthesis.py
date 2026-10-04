"""Step 3 — the report. Two schema-validated model calls (stage summaries, then causal chain,
factors and actions), each checked for citations and retried with the problems spelled out;
the final report is assembled here, not by the model, and re-checked. A claim that still has no
valid citation after the retries is dropped (never given a borrowed one) and counted in the
limitations. Provenance records the model, prompt versions and profile."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from vms_common.contracts.reasoning import (
    PHASES,
    Actor,
    CausalStep,
    ContributingFactors,
    EvidenceBundleV1,
    Factor,
    IncidentReportV1,
    PhaseName,
    PhaseSummary,
    RecommendedAction,
    SceneUnderstanding,
)
from vms_common.llm import Gateway, LLMError, render_prompt
from vms_common.logging import get_logger

from reasoning.domain import citations
from reasoning.domain.context import Context
from reasoning.domain.evidence import render_events, render_evidence

log = get_logger(__name__)

TASK = "incident_synthesis"
PHASES_PROMPT = ("incident_phases", "1.0")
CAUSAL_PROMPT = ("incident_causal", "1.0")


class _Cited(BaseModel):
    evidence: list[str] = Field(default_factory=list)


class _DraftActor(_Cited):
    ref: str = "subject"
    description: str


class _DraftPhase(_Cited):
    phase: str
    summary: str


class PhasesDraft(BaseModel):
    location: str = ""
    conditions: str = "not stated"
    actors: list[_DraftActor] = Field(default_factory=list)
    phases: list[_DraftPhase] = Field(default_factory=list)


class _DraftStep(_Cited):
    description: str


class _DraftFactor(_Cited):
    text: str


class _DraftAction(BaseModel):
    action: str
    priority: str = "medium"
    owner_role: str = "supervisor"


class CausalDraft(BaseModel):
    title: str = ""
    summary: str = ""
    causal_chain: list[_DraftStep] = Field(default_factory=list)
    primary: list[_DraftFactor] = Field(default_factory=list)
    environmental: list[_DraftFactor] = Field(default_factory=list)
    security_gaps: list[_DraftFactor] = Field(default_factory=list)
    recommended_actions: list[_DraftAction] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)


@dataclass
class SynthesisResult:
    report: IncidentReportV1 | None
    raw: str
    calls: int
    model: str
    dropped: int
    error: str | None = None


def _by_phase(drafts: list, allowed: set) -> list[tuple[PhaseName, object]]:
    """One summary per stage, keyed by the stage the label names; labels that name no stage in
    the evidence are dropped (the model may not invent stages)."""
    seen: dict[str, object] = {}
    for d in drafts:
        name = canon_phase(d.phase)
        if name in allowed and name not in seen:
            seen[name] = d
    order = {p: i for i, p in enumerate(PHASES)}
    return sorted(seen.items(), key=lambda kv: order[kv[0]])  # type: ignore[arg-type]


def canon_phase(raw: str) -> str | None:
    """The stage a model's phase label names, however it decorates it ("Stage action
    (12:01:45-12:01:46)", "Action phase"). First known stage name found, in time order."""
    low = raw.lower()
    return next((p for p in PHASES if p in low), None)


def _ids_problems(label: str, items: list[tuple[str, list[str]]], known: set[str]) -> list[str]:
    out: list[str] = []
    for name, ids in items:
        bad = [i for i in ids if i not in known]
        if bad:
            out.append(f"{label} '{name[:40]}' cites ids that do not exist: {', '.join(bad)}")
        if not [i for i in ids if i in known]:
            out.append(f"{label} '{name[:40]}' cites no evidence")
    return out


def _fix_ids(ids: list[str], known: set[str]) -> list[str]:
    """Tolerate the model writing `[ev-cap-01]` or `ev-cap-1`; anything else is left to fail."""
    fixed: list[str] = []
    for raw in ids:
        i = raw.strip().strip("[]").strip()
        if i not in known:
            parts = i.split("-")
            if len(parts) == 3 and parts[2].isdigit():
                candidate = f"{parts[0]}-{parts[1]}-{int(parts[2]):02d}"
                if candidate in known:
                    i = candidate
        fixed.append(i)
    return fixed


async def _ask(
    gateway: Gateway,
    prompt: str,
    model: type[BaseModel],
    validate,
    *,
    retries: int,
    meta: dict,
):
    """One drafting step with citation-driven retries. Returns (draft, raw text)."""
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    draft = None
    raw = ""
    for attempt in range(retries + 1):
        result = await gateway.chat(TASK, messages, response_model=model)
        meta["calls"] += result.attempts
        meta["model"] = f"{result.provider}/{result.model}"
        draft, raw = result.parsed, result.text
        found = validate(draft)
        if not found:
            return draft, raw
        log.info("synthesis_retry", attempt=attempt + 1, problems=found[:3])
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": "Your answer has problems:\n- "
                + "\n- ".join(found[:6])
                + "\nFix them and answer again with the complete JSON object. Cite only ids "
                "that appear in square brackets in the evidence.",
            },
        ]
    return draft, raw


async def synthesize(
    gateway: Gateway,
    ctx: Context,
    bundle: EvidenceBundleV1,
    *,
    incident_id: str,
    tz: ZoneInfo,
    retries: int,
    profile: str,
    when: str,
) -> SynthesisResult:
    known = bundle.evidence_ids()
    meta = {"calls": 0, "model": "unknown"}
    events_text = render_events(bundle)
    evidence_text = render_evidence(bundle, tz)
    phase_names = {p.phase for p in bundle.phases}

    def check_phases(d: PhasesDraft) -> list[str]:
        for x in d.actors:
            x.evidence = _fix_ids(x.evidence, known)
        for x in d.phases:
            x.evidence = _fix_ids(x.evidence, known)
        return _ids_problems("actor", [(a.ref, a.evidence) for a in d.actors], known) + (
            _ids_problems("stage summary", [(p.phase[:30], p.evidence) for p in d.phases], known)
        )

    try:
        p1_prompt = render_prompt(
            *PHASES_PROMPT,
            event_type=ctx.event_type.replace("_", " "),
            severity=ctx.severity,
            cameras=ctx.cameras,
            when=when,
            events=events_text,
            evidence=evidence_text,
        )
        phases_draft, raw1 = await _ask(
            gateway, p1_prompt, PhasesDraft, check_phases, retries=retries, meta=meta
        )
        assert isinstance(phases_draft, PhasesDraft)  # noqa: S101

        stage_lines = "\n".join(
            f"- {p.phase}: {p.summary} [{', '.join(p.evidence)}]" for p in phases_draft.phases
        )

        def check_causal(d: CausalDraft) -> list[str]:
            for group in (d.causal_chain, d.primary, d.environmental, d.security_gaps):
                for x in group:
                    x.evidence = _fix_ids(x.evidence, known)
            return (
                _ids_problems(
                    "causal step", [(s.description, s.evidence) for s in d.causal_chain], known
                )
                + _ids_problems("factor", [(f.text, f.evidence) for f in d.primary], known)
                + _ids_problems("factor", [(f.text, f.evidence) for f in d.environmental], known)
                + _ids_problems("factor", [(f.text, f.evidence) for f in d.security_gaps], known)
            )

        p2_prompt = render_prompt(
            *CAUSAL_PROMPT,
            event_type=ctx.event_type.replace("_", " "),
            severity=ctx.severity,
            cameras=ctx.cameras,
            when=when,
            location=phases_draft.location or "location not stated",
            conditions=phases_draft.conditions or "not stated",
            phases=stage_lines or "(none)",
            evidence=evidence_text,
        )
        causal_draft, raw2 = await _ask(
            gateway, p2_prompt, CausalDraft, check_causal, retries=retries, meta=meta
        )
        assert isinstance(causal_draft, CausalDraft)  # noqa: S101
    except LLMError as exc:
        return SynthesisResult(None, "", meta["calls"], meta["model"], 0, error=str(exc))

    report = IncidentReportV1(
        incident_id=incident_id,
        group_id=ctx.group_id,
        title=(
            causal_draft.title.strip()
            or f"{ctx.event_type.replace('_', ' ').title()} on {ctx.primary.camera_id}"
        )[:140],
        summary=causal_draft.summary.strip()
        or (phases_draft.phases[0].summary if phases_draft.phases else ""),
        event_type=ctx.event_type,
        severity=ctx.severity,
        window=bundle.window,
        cameras=bundle.cameras,
        scene_understanding=SceneUnderstanding(
            location=phases_draft.location.strip() or ctx.primary.camera_id,
            conditions=phases_draft.conditions.strip() or "not stated",
            actors=[
                Actor(ref=a.ref, description=a.description, evidence=a.evidence)
                for a in phases_draft.actors
            ],
        ),
        phase_analysis=[
            PhaseSummary(phase=name, summary=p.summary, evidence=p.evidence)
            for name, p in _by_phase(phases_draft.phases, phase_names)
        ],
        causal_chain=[
            CausalStep(step=i, description=s.description, evidence=s.evidence)
            for i, s in enumerate(causal_draft.causal_chain, start=1)
        ],
        contributing_factors=ContributingFactors(
            primary=[Factor(text=f.text, evidence=f.evidence) for f in causal_draft.primary],
            environmental=[
                Factor(text=f.text, evidence=f.evidence) for f in causal_draft.environmental
            ],
            security_gaps=[
                Factor(text=f.text, evidence=f.evidence) for f in causal_draft.security_gaps
            ],
        ),
        recommended_actions=[
            RecommendedAction(
                action=a.action,
                priority=a.priority if a.priority in ("low", "medium", "high") else "medium",
                owner_role=a.owner_role,
            )
            for a in causal_draft.recommended_actions
        ],
        confidence=causal_draft.confidence,
        limitations=list(causal_draft.limitations),
    )

    dropped = 0
    if citations.problems(report, known):
        report, dropped = citations.prune(report, known)
    limitations = list(report.limitations)
    if dropped:
        limitations.append(f"{dropped} statement(s) were left out because they cited no evidence.")
    cited = sorted(report.cited_ids())
    report = report.model_copy(
        update={
            "limitations": limitations,
            "evidence_index": cited,
            "provenance": {
                "synthesis_model": meta["model"],
                "prompt_versions": [PHASES_PROMPT[1], CAUSAL_PROMPT[1]],
                "profile": profile,
                "model_calls": meta["calls"],
                "dropped_claims": dropped,
            },
        }
    )
    if not report.causal_chain and not report.phase_analysis:
        return SynthesisResult(
            None,
            raw1 + "\n" + raw2,
            meta["calls"],
            meta["model"],
            dropped,
            error="no statement in the draft cited valid evidence",
        )
    return SynthesisResult(report, raw1 + "\n" + raw2, meta["calls"], meta["model"], dropped)


__all__ = ["synthesize", "SynthesisResult", "PhaseName"]
