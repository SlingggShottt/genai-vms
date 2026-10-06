"""Citation checks for an incident report (design §8.5, CLAUDE.md "every GenAI claim cites
evidence ids"). Pure.

A claim is a causal step, a contributing factor, a stage summary or an actor. Each must cite at
least one id that exists in the evidence bundle. `problems` lists what is wrong, worded for the
model (it is sent back on a retry); `prune` is the last resort when retries run out: claims
without a valid citation are *dropped* — never given a borrowed citation — and counted.
"""

from __future__ import annotations

from vms_common.contracts.reasoning import IncidentReportV1


def _claims(report: IncidentReportV1):
    for a in report.scene_understanding.actors:
        yield f"actor '{a.ref}'", a.evidence
    for p in report.phase_analysis:
        yield f"summary of stage {p.phase}", p.evidence
    for s in report.causal_chain:
        yield f"causal step {s.step}", s.evidence
    cf = report.contributing_factors
    for group, items in (
        ("primary", cf.primary),
        ("environmental", cf.environmental),
        ("security gap", cf.security_gaps),
    ):
        for i, f in enumerate(items, start=1):
            yield f"{group} factor {i}", f.evidence


def problems(report: IncidentReportV1, known_ids: set[str]) -> list[str]:
    found: list[str] = []
    for label, ids in _claims(report):
        unknown = [i for i in ids if i not in known_ids]
        if unknown:
            found.append(f"{label} cites ids that do not exist: {', '.join(unknown)}")
        if not [i for i in ids if i in known_ids]:
            found.append(f"{label} cites no evidence")
    return found


def prune(report: IncidentReportV1, known_ids: set[str]) -> tuple[IncidentReportV1, int]:
    """Drop every claim that has no valid citation and strip invalid ids from the rest."""
    dropped = 0

    def keep(ids: list[str]) -> list[str]:
        return [i for i in dict.fromkeys(ids) if i in known_ids]

    actors = []
    for a in report.scene_understanding.actors:
        ev = keep(a.evidence)
        if ev:
            actors.append(a.model_copy(update={"evidence": ev}))
        else:
            dropped += 1
    phases = []
    for p in report.phase_analysis:
        ev = keep(p.evidence)
        if ev:
            phases.append(p.model_copy(update={"evidence": ev}))
        else:
            dropped += 1
    steps = []
    for s in report.causal_chain:
        ev = keep(s.evidence)
        if ev:
            steps.append(s.model_copy(update={"evidence": ev, "step": len(steps) + 1}))
        else:
            dropped += 1

    def factors(items):
        nonlocal dropped
        out = []
        for f in items:
            ev = keep(f.evidence)
            if ev:
                out.append(f.model_copy(update={"evidence": ev}))
            else:
                dropped += 1
        return out

    cf = report.contributing_factors
    pruned = report.model_copy(
        update={
            "scene_understanding": report.scene_understanding.model_copy(update={"actors": actors}),
            "phase_analysis": phases,
            "causal_chain": steps,
            "contributing_factors": cf.model_copy(
                update={
                    "primary": factors(cf.primary),
                    "environmental": factors(cf.environmental),
                    "security_gaps": factors(cf.security_gaps),
                }
            ),
        }
    )
    return pruned, dropped
