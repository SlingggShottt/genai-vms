"""The judge: scores assistant answers and incident reports against the records behind them.

All model calls go through the gateway's `eval_judge` task (`config/models.yaml`, key
`evaluation.judge`, a different model family from the generators), with the prompt in
`libs/vms_common/llm/prompts/eval_judge/1.0.md`. Also here: the checks that need no model at all
(does a report validate against `incident.v1`, does every id it cites exist, how many cite nothing).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from vms_common.contracts.reasoning import IncidentReportV1
from vms_common.llm import LLMError, render_prompt
from vms_common.llm.registry import JUDGE_TASK

PROMPT = "eval_judge"
VERSION = "1.0"

EXPECTATIONS = {
    "answer": "",
    "refuse": (
        "it says plainly that it cannot or will not do this, and does not guess, pretend, or "
        "answer from unrelated records"
    ),
    "no_data": "it says that no matching records exist, instead of inventing some",
}
_TAG = re.compile(r"\[([EIS]):([0-9a-f]{8})\]")


class CitationJudgement(BaseModel):
    tag: str
    supports: Literal["yes", "partly", "no"]


class AnswerJudgement(BaseModel):
    faithfulness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    citations: list[CitationJudgement] = Field(default_factory=list)
    problem: str = Field(default="", max_length=200)


class ReportJudgement(BaseModel):
    accuracy: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    causality: int = Field(ge=1, le=5)
    actionability: int = Field(ge=1, le=5)
    problem: str = Field(default="", max_length=200)


# ---- assistant answers --------------------------------------------------------------------------


def _args_text(arguments: dict | None) -> str:
    return ", ".join(f"{k}={v}" for k, v in (arguments or {}).items() if v not in (None, "", []))


def records_seen(tools: list[dict], *, max_lines: int = 14) -> list[str]:
    """What the assistant's lookups were asked and returned, as plain lines. The arguments matter:
    an answer about 4 October built on a lookup of "last 24 hours" is not about 4 October."""
    out: list[str] = []
    for t in tools:
        asked = f"lookup {t.get('tool', '?')}({_args_text(t.get('arguments'))})"
        out.append(f"{asked}: {t.get('summary') or ''}"[:320])
        out += [str(x)[:320] for x in (t.get("lines") or [])]
    return out[:max_lines]


def _mentions_camera(arguments: dict | None, camera: str) -> bool:
    a = arguments or {}
    return a.get("camera") == camera or camera in (a.get("cameras") or [])


def _mentions_day(arguments: dict | None, day: str) -> bool:
    a = arguments or {}
    return any(day in str(a.get(k) or "") for k in ("when", "date", "day", "start"))


def scope_check(transcript: dict) -> dict:
    """What can be checked without any model: the question knows its camera, its day and which
    lookup is right (`tool`), so compare them with what the assistant actually asked for.
    Each value is True/False, or None where the question has no such expectation."""
    out: dict = {"routed": None, "camera_scoped": None, "day_scoped": None}
    if transcript.get("expect") != "answer":
        return out
    tools = transcript.get("tools") or []
    if transcript.get("tool"):
        out["routed"] = bool(tools) and tools[0].get("tool") == transcript["tool"]
    if transcript.get("camera"):
        out["camera_scoped"] = any(
            _mentions_camera(t.get("arguments"), transcript["camera"]) for t in tools
        )
    if transcript.get("day"):
        out["day_scoped"] = any(_mentions_day(t.get("arguments"), transcript["day"]) for t in tools)
    return out


def tags_written(answer: str) -> list[str]:
    """The `[E:abcd1234]` tags the answer text itself contains, in order, without repeats."""
    seen: list[str] = []
    for kind, ident in _TAG.findall(answer):
        tag = f"{kind}:{ident}"
        if tag not in seen:
            seen.append(tag)
    return seen


def answer_prompt(transcript: dict, expect: str) -> str:
    cited = []
    if not transcript.get("consulted_only"):
        cited = [
            {"tag": f"{c['kind']}:{c['tag']}", "label": str(c.get("label", ""))[:300]}
            for c in transcript.get("citations", [])
        ]
    return render_prompt(
        PROMPT,
        VERSION,
        kind="answer",
        question=transcript["question"],
        expectation=EXPECTATIONS.get(expect, ""),
        answer=transcript["answer"],
        records=records_seen(transcript.get("tools", [])),
        cited=cited,
    )


async def judge_answer(gateway, transcript: dict, expect: str) -> AnswerJudgement | None:
    """None when the judge could not be reached or answered nonsense (counted by the caller)."""
    prompt = answer_prompt(transcript, expect)
    try:
        result = await gateway.chat(
            JUDGE_TASK, [{"role": "user", "content": prompt}], response_model=AnswerJudgement
        )
    except (LLMError, ValidationError):
        return None
    judgement = result.parsed
    assert isinstance(judgement, AnswerJudgement)  # noqa: S101 - validated by the gateway
    return judgement


# The first worked example in the judge prompt. A 3B judge copies its wording into the answers it
# scores (measured: see the results file), so the problems that start like it are counted.
EXAMPLE_PROBLEM_PREFIX = "claims 4 october but the lookup covered"
EVENT_TYPES = ("abandoned object", "crowding", "intrusion", "loitering")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def citation_consistency(transcript: dict) -> list[dict]:
    """For each event tag the answer writes that resolves to a record, does the sentence it sits in
    agree with that record on event type and camera, with no model involved? 'contradicted' when the
    sentence names another camera than the record's (and not the record's), or another event type
    and not the record's; 'consistent' when it names the record's type and no other camera;
    'unclear' otherwise. Judged against the whole sentence, so two tags in one sentence are not
    told apart. Only event records (`[E:...]`, labelled "<type> on <camera>") are checked."""
    records = {
        f"{c['kind']}:{c['tag']}": c
        for c in transcript.get("citations", [])
        if c.get("kind") == "E" and " on " in str(c.get("label", ""))
    }
    cameras = {c.get("camera") for c in transcript.get("citations", []) if c.get("camera")}
    if transcript.get("camera"):
        cameras.add(transcript["camera"])
    out = []
    for sentence in _SENTENCE.split(transcript.get("answer") or ""):
        text = sentence.lower().replace("_", " ")
        for kind, ident in _TAG.findall(sentence):
            record = records.get(f"{kind}:{ident}")
            if not record:
                continue
            kind_word, _, camera = str(record["label"]).partition(" on ")
            kind_word = kind_word.lower().replace("_", " ")
            other_cameras = [c for c in cameras if c != camera and c.lower() in text]
            other_type = any(t != kind_word and t in text for t in EVENT_TYPES)
            has_type = kind_word in text
            if (other_cameras and camera.lower() not in text) or (other_type and not has_type):
                verdict = "contradicted"
            elif has_type and not other_cameras:
                verdict = "consistent"
            else:
                verdict = "unclear"
            out.append({"tag": f"{kind}:{ident}", "verdict": verdict})
    return out


CAP_WHEN_FLAWED = 3


def with_adjusted(verdict: AnswerJudgement) -> dict:
    """The verdict as a dict plus `faithfulness_adj` / `relevance_adj`: the scores capped at 3 when
    the judge itself wrote down a problem. Measured on this system, a 3B judge names the defect
    correctly ("claims 4 October but the lookup covered the last 24 hours") and then still scores 5,
    so the raw score alone flatters. Both are reported."""
    out = verdict.model_dump()
    flawed = bool(verdict.problem.strip())
    out["faithfulness_adj"] = (
        min(verdict.faithfulness, CAP_WHEN_FLAWED) if flawed else verdict.faithfulness
    )
    out["relevance_adj"] = min(verdict.relevance, CAP_WHEN_FLAWED) if flawed else verdict.relevance
    return out


# ---- incident reports ---------------------------------------------------------------------------


def evidence_texts(evidence: dict | None) -> dict[str, str]:
    """{evidence id: the text it stands for} from a stored `incidents.evidence` bundle."""
    out: dict[str, str] = {}
    if not evidence:
        return out
    for p in evidence.get("phases", []):
        for view in p.get("views", []):
            cap = view.get("caption") or {}
            if cap.get("id"):
                out[cap["id"]] = (
                    f"({p.get('phase')}, {view.get('camera_id')}) {cap.get('text', '')}"
                )
            for qa in view.get("vqa", []):
                out[qa["id"]] = f"({p.get('phase')}, {view.get('camera_id')}) {qa['q']} {qa['a']}"
            for fr in view.get("frames", []):
                out[fr["id"]] = f"frame at {fr.get('ts', '')}"
    for e in evidence.get("events", []):
        out[e["id"]] = (
            f"detector event on {e.get('camera_id')}: {e.get('caption') or e.get('event_type')}"
        )
    return out


def report_prompt(report: IncidentReportV1, texts: dict[str, str]) -> str:
    def cites(ids: list[str]) -> str:
        return " [" + ", ".join(ids) + "]" if ids else ""

    stages = [f"{p.phase}: {p.summary}{cites(p.evidence)}" for p in report.phase_analysis]
    chain = [f"{s.step}. {s.description}{cites(s.evidence)}" for s in report.causal_chain]
    actions = [f"{a.action}" for a in report.recommended_actions]
    wanted = [i for i in report.evidence_index if i in texts][:40]
    return render_prompt(
        PROMPT,
        VERSION,
        kind="report",
        title=report.title,
        summary=report.summary,
        stages=stages,
        chain=chain,
        actions=actions,
        evidence=[{"id": i, "text": texts[i][:260]} for i in wanted],
    )


async def judge_report(
    gateway, report: IncidentReportV1, texts: dict[str, str]
) -> ReportJudgement | None:
    prompt = report_prompt(report, texts)
    try:
        result = await gateway.chat(
            JUDGE_TASK, [{"role": "user", "content": prompt}], response_model=ReportJudgement
        )
    except (LLMError, ValidationError):
        return None
    judgement = result.parsed
    assert isinstance(judgement, ReportJudgement)  # noqa: S101 - validated by the gateway
    return judgement


def check_report(raw: dict | None, texts: dict[str, str]) -> dict:
    """Checks that need no model: does the stored report validate against `incident.v1`, and does
    every id
    it cites exist in its own evidence index and in the evidence bundle."""
    if raw is None:
        return {"has_report": False, "valid": False}
    try:
        report = IncidentReportV1.model_validate(raw)
    except ValidationError as exc:
        return {"has_report": True, "valid": False, "error": exc.errors()[0]["msg"][:120]}
    cited = report.cited_ids()
    index = set(report.evidence_index)
    return {
        "has_report": True,
        "valid": True,
        "cited": len(cited),
        "cited_not_in_index": len(cited - index),
        "cited_not_in_bundle": len(cited - set(texts)) if texts else None,
        "claims_left_out": int(
            next(
                (m.group(1) for s in report.limitations if (m := re.match(r"(\d+) statement", s))),
                0,
            )
        ),
    }
