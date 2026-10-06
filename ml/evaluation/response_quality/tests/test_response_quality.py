"""Tests for the response-quality evaluation: the question set, the stream reading, the judge's
prompts and checks, the numbers and the human sheets. No model, no network."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest
from vms_common.contracts.reasoning import IncidentReportV1
from vms_common.llm import LLMError
from vms_common.llm.registry import JUDGE_TASK
from vms_common.llm.testing import FakeGateway

RQ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RQ))  # the modules import each other by name
sys.path.insert(0, str(RQ.parent))  # and `stats`


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"rq_{name}", RQ / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"rq_{name}"] = module
    spec.loader.exec_module(module)
    return module


questions = load("questions")
collect = load("collect")
judge = load("judge")
aggregate = load("aggregate")
run = load("run")

CAMS = ["bus-g331", "bus-g340", "cam01"]
DAYS = [date(2026, 10, 4), date(2026, 10, 6)]
TYPES = ["abandoned_object", "crowding", "intrusion", "loitering"]


# ---- the questions ------------------------------------------------------------------------------


def test_there_are_at_least_sixty_distinct_questions_for_a_realistic_scope() -> None:
    for seed in (1, 7, 99):
        qs = questions.build_questions(CAMS, DAYS, TYPES, seed=seed)
        assert len(qs) >= 60
        assert len({q.text for q in qs}) == len(qs) and len({q.qid for q in qs}) == len(qs)
        assert {q.expect for q in qs} == {"answer", "refuse", "no_data"}


def test_the_set_is_deterministic_and_the_seed_matters() -> None:
    a = questions.build_questions(CAMS, DAYS, TYPES, seed=7)
    assert a == questions.build_questions(CAMS, DAYS, TYPES, seed=7)
    assert a != questions.build_questions(CAMS, DAYS, TYPES, seed=8)


def test_questions_only_name_cameras_and_days_that_exist_apart_from_the_deliberate_gaps() -> None:
    qs = questions.build_questions(CAMS, DAYS, TYPES)
    for q in qs:
        if q.expect == "answer":
            assert "camera-99" not in q.text and "2000" not in q.text and "1 January" not in q.text
    assert any("camera-99" in q.text for q in qs if q.expect == "no_data")
    assert any(q.category == "out_of_scope" for q in qs)


def test_dates_are_spelled_the_way_people_write_them() -> None:
    d = date(2026, 10, 4)
    assert [questions.spell(d, i) for i in range(4)] == [
        "4 October",
        "October 4",
        "2026-10-04",
        "the 4th of October",
    ]
    ordinals = {n: questions._ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 30)}
    assert ordinals == dict(
        zip(
            (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 30),
            ["st", "nd", "rd", "th", "th", "th", "th", "st", "nd", "rd", "th"],
            strict=True,
        )
    )


def test_a_scope_without_cameras_days_or_types_is_refused() -> None:
    for args in (([], DAYS, TYPES), (CAMS, [], TYPES), (CAMS, DAYS, [])):
        with pytest.raises(ValueError, match="at least one"):
            questions.build_questions(*args)


# ---- reading the stream -------------------------------------------------------------------------

STREAM = (
    'event: tool_call\ndata: {"type": "tool_call", "tool": "list_events", '
    '"arguments": {"when": "today"}}\n\n'
    ": keep-alive\n\n"
    'event: tool_result\ndata: {"type": "tool_result", "tool": "list_events", '
    '"summary": "3 verified event(s)", "lines": ["[E:abcd1234] loitering"], "cites": []}\n\n'
    'event: token\ndata: {"type": "token", "text": "3 verified "}\n\n'
    'event: token\ndata: {"type": "token", "text": "events [E:abcd1234]."}\n\n'
    'event: citation\ndata: {"type": "citation", "citations": [{"kind": "E", "tag": '
    '"abcd1234", "label": "loitering"}], "unknown": [], "consulted": false}\n\n'
    'event: done\ndata: {"type": "done", "message_id": "m1"}\n\n'
)


def test_a_stream_is_read_into_events_skipping_comments_and_garbage() -> None:
    events = collect.parse_sse(STREAM.replace("\n", "\r\n") + "event: x\ndata: not json\n\n")
    assert [e["type"] for e in events] == [
        "tool_call",
        "tool_result",
        "token",
        "token",
        "citation",
        "done",
    ]


def test_a_turn_folds_into_a_transcript_with_the_lookup_and_its_arguments() -> None:
    t = collect.fold("q1", "list_events", "What happened?", collect.parse_sse(STREAM), 2.345)
    assert t.answer == "3 verified events [E:abcd1234]."
    assert t.tools == [
        {
            "tool": "list_events",
            "summary": "3 verified event(s)",
            "lines": ["[E:abcd1234] loitering"],
            "arguments": {"when": "today"},
            "cites": [],
        }
    ]
    assert t.citations[0]["tag"] == "abcd1234" and not t.consulted_only and t.seconds == 2.35


def test_an_error_event_is_kept_and_the_citation_flags_are_read() -> None:
    events = collect.parse_sse(
        'event: error\ndata: {"type": "error", "message": "model down"}\n\n'
        'event: citation\ndata: {"type": "citation", "citations": [], "unknown": ["E:ffffffff"], '
        '"consulted": true}\n\n'
    )
    t = collect.fold("q", "c", "?", events, 1)
    assert t.error == "model down" and t.consulted_only and t.unknown_tags == ["E:ffffffff"]


def test_the_assistant_client_waits_out_a_rate_limit_and_then_succeeds(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(collect.time, "sleep", sleeps.append)
    calls = {"messages": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "t"})
        if path.endswith("/assistant/sessions") and request.method == "POST":
            return httpx.Response(201, json={"id": "s1"})
        if path.endswith("/messages"):
            calls["messages"] += 1
            if calls["messages"] <= 2:
                return httpx.Response(429, headers={"Retry-After": "7"}, json={})
            return httpx.Response(200, text=STREAM)
        return httpx.Response(204)

    a = collect.Assistant("http://t/api/v1", "e", "p", transport=httpx.MockTransport(handler))
    t = a.ask("q1", "c", "What happened?")
    assert t.answer.startswith("3 verified") and not t.error
    assert sleeps == [7.5, 7.5]  # waited the full Retry-After, plus half a second, twice


def test_the_rate_limit_is_waited_out_when_opening_a_session_too(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(collect.time, "sleep", sleeps.append)
    state = {"sessions": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "t"})
        if path.endswith("/assistant/sessions") and request.method == "POST":
            state["sessions"] += 1
            if state["sessions"] == 1:
                return httpx.Response(429, headers={"Retry-After": "12"}, json={})
            return httpx.Response(201, json={"id": "s1"})
        if path.endswith("/messages"):
            return httpx.Response(200, text=STREAM)
        return httpx.Response(204)

    a = collect.Assistant("http://t/api/v1", "e", "p", transport=httpx.MockTransport(handler))
    assert a.ask("q", "c", "?").answer.startswith("3 verified")
    assert sleeps == [12.5]


def test_the_assistant_client_gives_up_after_waiting_and_says_so() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path.endswith("/assistant/sessions") and request.method == "POST":
            return httpx.Response(201, json={"id": "s1"})
        return httpx.Response(429, headers={"Retry-After": "0"}, json={})

    a = collect.Assistant(
        "http://t/api/v1", "e", "p", max_waits=2, transport=httpx.MockTransport(handler)
    )
    t = a.ask("q1", "c", "?")
    assert "rate limited" in t.error and t.answer == ""


# ---- the judge ----------------------------------------------------------------------------------

TRANSCRIPT = {
    "qid": "q1",
    "category": "list_events",
    "question": "What happened on cam01?",
    "answer": "One intrusion at 21:57 [E:abcd1234]. Nobody was hurt [E:00000000].",
    "tools": [
        {
            "tool": "list_events",
            "summary": "1 verified event(s)",
            "lines": ["[E:abcd1234] intrusion 21:57"],
        }
    ],
    "citations": [{"kind": "E", "tag": "abcd1234", "label": "intrusion on cam01 at 21:57"}],
    "consulted_only": False,
    "unknown_tags": ["E:00000000"],
    "error": "",
}


def test_tags_written_in_an_answer_are_found_in_order_without_repeats() -> None:
    assert judge.tags_written(
        "A [E:abcd1234] b [I:0123abcd] c [E:abcd1234] [S:0a1b2c3d] [S:zzzz]"
    ) == [
        "E:abcd1234",
        "I:0123abcd",
        "S:0a1b2c3d",
    ]


def test_the_answer_prompt_has_the_question_the_answer_the_records_and_what_it_cites() -> None:
    prompt = judge.answer_prompt(TRANSCRIPT, "answer")
    for needle in (
        "What happened on cam01?",
        "One intrusion at 21:57",
        "lookup list_events(): 1 verified event(s)",
        "[E:abcd1234] intrusion on cam01 at 21:57",
        "faithfulness",
        "relevance",
    ):
        assert needle in prompt
    assert "What a good answer does here" not in prompt  # nothing special is expected of it


def test_what_a_refusal_or_an_empty_result_should_look_like_is_told_to_the_judge() -> None:
    assert "cannot or will not" in judge.answer_prompt(TRANSCRIPT, "refuse")
    assert "no matching records exist" in judge.answer_prompt(TRANSCRIPT, "no_data")


def test_citations_the_model_did_not_make_are_not_shown_as_its_own() -> None:
    consulted = TRANSCRIPT | {"consulted_only": True}
    prompt = judge.answer_prompt(consulted, "answer")
    assert (
        "(the answer cites nothing)" in prompt
        and "intrusion on cam01 at 21:57" not in prompt.split("Records the answer cites")[1]
    )


async def test_the_judge_parses_its_verdict_through_the_gateway() -> None:
    gateway = FakeGateway(
        {
            JUDGE_TASK: {
                "faithfulness": 4,
                "relevance": 5,
                "citations": [{"tag": "E:abcd1234", "supports": "yes"}],
                "problem": "",
            }
        }
    )
    v = await judge.judge_answer(gateway, TRANSCRIPT, "answer")
    assert (v.faithfulness, v.relevance, v.citations[0].supports) == (4, 5, "yes")
    assert (
        gateway.calls[0].task == JUDGE_TASK and "What happened on cam01?" in gateway.calls[0].prompt
    )


async def test_an_unreachable_or_nonsense_judge_gives_none_not_a_crash() -> None:
    class Down:
        async def chat(self, *a, **k):
            raise LLMError("no model")

    assert await judge.judge_answer(Down(), TRANSCRIPT, "answer") is None
    out_of_range = FakeGateway({JUDGE_TASK: {"faithfulness": 9, "relevance": 1}})
    assert await judge.judge_answer(out_of_range, TRANSCRIPT, "answer") is None


def test_the_judge_is_shown_what_each_lookup_was_asked_not_only_what_it_returned() -> None:
    tools = [
        {
            "tool": "list_events",
            "arguments": {"when": "last 24 hours", "camera": "cam01", "limit": 10, "type": None},
            "summary": "No verified events.",
            "lines": [],
        }
    ]
    lines = judge.records_seen(tools)
    assert lines == [
        "lookup list_events(when=last 24 hours, camera=cam01, limit=10): No verified events."
    ]  # an empty argument is not shown


def tr(**over) -> dict:
    base = {
        "expect": "answer",
        "tool": "list_events",
        "camera": "cam01",
        "day": "2026-10-04",
        "tools": [
            {"tool": "list_events", "arguments": {"when": "2026-10-04", "camera": "cam01"}},
        ],
    }
    return base | over


def test_scope_checks_compare_what_was_asked_with_what_the_lookup_used() -> None:
    assert judge.scope_check(tr()) == {"routed": True, "camera_scoped": True, "day_scoped": True}
    wrong_tool = tr(tools=[{"tool": "count_objects", "arguments": {"camera": "cam01"}}])
    assert judge.scope_check(wrong_tool) == {
        "routed": False,
        "camera_scoped": True,
        "day_scoped": False,
    }
    default_window = tr(
        tools=[
            {"tool": "list_events", "arguments": {"when": "last 24 hours", "cameras": ["cam01"]}}
        ]
    )
    got = judge.scope_check(default_window)
    assert got["routed"] and got["camera_scoped"] and got["day_scoped"] is False


def test_scope_checks_say_nothing_where_the_question_expects_nothing() -> None:
    nothing = {"routed": None, "camera_scoped": None, "day_scoped": None}
    assert judge.scope_check(tr(expect="refuse")) == nothing
    assert judge.scope_check(tr(expect="no_data")) == nothing
    open_ended = tr(tool=None, camera=None, day=None)
    assert judge.scope_check(open_ended) == nothing
    assert judge.scope_check(tr(tools=[]))["routed"] is False  # it looked nothing up


def test_scope_rates_are_summarised_over_the_questions_that_have_the_expectation() -> None:
    rows = [row("a", "x", 5, 5), row("b", "x", 5, 5), row("c", "x", 5, 5)]
    rows[0]["transcript"]["scope"] = {"routed": True, "camera_scoped": True, "day_scoped": False}
    rows[1]["transcript"]["scope"] = {"routed": False, "camera_scoped": None, "day_scoped": False}
    rows[2]["transcript"]["scope"] = {"routed": None, "camera_scoped": None, "day_scoped": None}
    s = aggregate.summarise_answers(rows)["scope"]
    assert s["routed"] == {"questions": 2, "rate": 0.5}
    assert s["camera_scoped"] == {"questions": 1, "rate": 1.0}
    assert s["day_scoped"] == {"questions": 2, "rate": 0.0}


def test_every_answerable_question_knows_its_tool_and_those_with_a_day_know_it() -> None:
    qs = questions.build_questions(CAMS, DAYS, TYPES)
    for q in qs:
        if q.expect == "answer":
            assert q.tool in {
                "count_objects", "list_events", "list_incidents", "get_timeline",
                "get_daily_report", "search_footage",
            }  # fmt: skip
        else:
            assert q.tool is None
        if q.day:
            assert date.fromisoformat(q.day)
    assert any(q.category == "count_events" and q.tool == "list_events" for q in qs)
    assert all(q.camera in CAMS for q in qs if q.camera and q.expect == "answer")


# ---- incident reports ---------------------------------------------------------------------------

BUNDLE = {
    "events": [
        {
            "id": "ev-evt-01",
            "camera_id": "cam01",
            "event_type": "intrusion",
            "caption": "A person at the gate.",
        }
    ],
    "phases": [
        {
            "phase": "action",
            "views": [
                {
                    "camera_id": "cam01",
                    "caption": {"id": "ev-cap-01", "text": "A man climbs the gate."},
                    "vqa": [{"id": "ev-qa-01", "q": "Is anyone crossing a barrier?", "a": "Yes"}],
                    "frames": [{"id": "ev-fr-01", "ts": "2026-10-04T12:00:00Z", "uri": "s3://x"}],
                }
            ],
        }
    ],
}


def report(**over) -> dict:
    base = {
        "schema_version": "incident.v1",
        "incident_id": "i1",
        "group_id": None,
        "title": "Gate intrusion",
        "summary": "A man climbed the gate.",
        "event_type": "intrusion",
        "severity": "high",
        "window": {"start": "2026-10-04T12:00:00Z", "end": "2026-10-04T12:00:30Z"},
        "cameras": ["cam01"],
        "scene_understanding": {"location": "gate", "conditions": "day", "actors": []},
        "phase_analysis": [
            {"phase": "action", "summary": "He climbs.", "evidence": ["ev-cap-01", "ev-qa-01"]}
        ],
        "causal_chain": [
            {"step": 1, "description": "He crossed the barrier.", "evidence": ["ev-qa-01"]}
        ],
        "contributing_factors": {"primary": [], "environmental": [], "security_gaps": []},
        "recommended_actions": [
            {"action": "Check the gate lock.", "priority": "high", "owner_role": "supervisor"}
        ],
        "confidence": 0.8,
        "limitations": ["2 statement(s) were left out because they cited no evidence."],
        "evidence_index": ["ev-cap-01", "ev-qa-01", "ev-fr-01"],
        "provenance": {},
    }
    return base | over


def test_evidence_ids_are_mapped_to_the_text_they_stand_for() -> None:
    texts = judge.evidence_texts(BUNDLE)
    assert texts["ev-cap-01"].endswith("A man climbs the gate.")
    assert "Is anyone crossing a barrier? Yes" in texts["ev-qa-01"]
    assert texts["ev-evt-01"].startswith("detector event on cam01")
    assert judge.evidence_texts(None) == {}


def test_a_valid_report_passes_the_checks_and_counts_what_was_left_out() -> None:
    check = judge.check_report(report(), judge.evidence_texts(BUNDLE))
    assert check == {
        "has_report": True,
        "valid": True,
        "cited": 2,
        "cited_not_in_index": 0,
        "cited_not_in_bundle": 0,
        "claims_left_out": 2,
    }


def test_dangling_citations_and_schema_errors_are_found() -> None:
    texts = judge.evidence_texts(BUNDLE)
    dangling = report(causal_chain=[{"step": 1, "description": "x", "evidence": ["ev-qa-99"]}])
    c = judge.check_report(dangling, texts)
    assert c["valid"] and c["cited_not_in_index"] == 1 and c["cited_not_in_bundle"] == 1
    broken = report(severity="catastrophic")
    c = judge.check_report(broken, texts)
    assert c["has_report"] and not c["valid"] and c["error"]
    assert judge.check_report(None, texts) == {"has_report": False, "valid": False}


async def test_the_report_judge_sees_the_stages_the_chain_and_the_evidence_it_cites() -> None:
    texts = judge.evidence_texts(BUNDLE)
    model = IncidentReportV1.model_validate(report())
    prompt = judge.report_prompt(model, texts)
    for needle in (
        "Gate intrusion",
        "action: He climbs. [ev-cap-01, ev-qa-01]",
        "1. He crossed the barrier.",
        "Check the gate lock.",
        "[ev-cap-01]",
        "A man climbs the gate.",
    ):
        assert needle in prompt
    gateway = FakeGateway(
        {JUDGE_TASK: {"accuracy": 4, "completeness": 3, "causality": 4, "actionability": 2}}
    )
    v = await judge.judge_report(gateway, model, texts)
    assert (v.accuracy, v.actionability) == (4, 2)


# ---- the numbers --------------------------------------------------------------------------------


def row(
    qid, cat, faith, rel, cites=(), *, expect="answer", answer="a", error="", written=(), unknown=()
):
    t = {
        "qid": qid,
        "answer": answer,
        "error": error,
        "seconds": 2.0,
        "tools": [],
        "question": qid,
        "citations": [{"kind": "E", "tag": "x", "label": "y"}] if cites else [],
        "consulted_only": False,
        "tags_written": list(written),
        "unknown_tags": list(unknown),
    }
    j = (
        None
        if faith is None
        else {
            "faithfulness": faith,
            "relevance": rel,
            "citations": [{"tag": "E:x", "supports": s} for s in cites],
            "problem": "",
        }
    )
    return {"qid": qid, "category": cat, "expect": expect, "transcript": t, "judgement": j}


def test_answer_numbers_are_the_hand_computed_ones() -> None:
    rows = [
        row("a", "count", 5, 5, ("yes", "yes"), written=("E:1", "E:2")),
        row("b", "count", 3, 4, ("partly", "no"), written=("E:3",), unknown=("E:3",)),
        row("c", "search", 1, 2, ()),
        row("d", "search", None, None, (), answer=""),  # no answer: not judged, not a judge failure
        row("e", "search", None, None, (), answer="text"),  # an answer the judge could not score
    ]
    s = aggregate.summarise_answers(rows)
    assert (s["questions"], s["answered"], s["judged"], s["judge_failures"]) == (5, 4, 3, 1)
    assert s["faithfulness"]["mean"] == 3.0 and s["relevance"]["mean"] == pytest.approx(
        3.667, abs=1e-3
    )
    assert s["faithfulness_4_or_5"] == pytest.approx(1 / 3, abs=1e-3)
    # 2 yes + 1 partly + 1 no checked: strict 2/4, lenient (2 + 0.5)/4
    assert s["citation_precision"] == {"checked": 4, "strict": 0.5, "lenient": 0.625}
    assert (s["tags_written"], s["tags_that_matched_no_record"]) == (3, 1)
    assert s["by_category"]["count"]["faithfulness"]["mean"] == 4.0
    assert s["by_category"]["search"]["questions"] == 3


def test_report_numbers_count_schema_validity_and_citation_integrity() -> None:
    good = {
        "has_report": True,
        "valid": True,
        "cited": 3,
        "cited_not_in_index": 0,
        "cited_not_in_bundle": 0,
        "claims_left_out": 2,
    }
    bad = {"has_report": True, "valid": False, "error": "x"}
    rows = [
        {
            "incident_id": "1",
            "check": good,
            "judgement": {"accuracy": 4, "completeness": 3, "causality": 5, "actionability": 2},
        },
        {"incident_id": "2", "check": bad, "judgement": None},
        {"incident_id": "3", "check": {"has_report": False, "valid": False}, "judgement": None},
    ]
    s = aggregate.summarise_reports(rows)
    assert (s["incidents"], s["with_a_report"], s["schema_valid"], s["schema_valid_rate"]) == (
        3,
        2,
        1,
        0.5,
    )
    assert s["statements_left_out_for_citing_nothing"] == 2 and s["judged"] == 1
    assert s["causality"]["mean"] == 5.0 and s["actionability"]["mean"] == 2.0


# ---- the human sheets ---------------------------------------------------------------------------


def test_the_human_sample_is_a_fifth_with_every_category_in_it_and_is_reproducible() -> None:
    rows = [row(f"q{i:02d}", "A" if i < 40 else "B", 4, 4) for i in range(50)] + [
        row("z", "C", 3, 3)
    ]
    sample = aggregate.sample_for_humans(rows)
    cats = {r["category"] for r in sample}
    assert cats == {"A", "B", "C"}
    assert 8 <= len(sample) <= 14  # about 20 % of 51, one at least from the smallest group
    assert [r["qid"] for r in sample] == [r["qid"] for r in aggregate.sample_for_humans(rows)]
    assert [r["qid"] for r in sample] != [
        r["qid"] for r in aggregate.sample_for_humans(rows, seed=8)
    ]


def test_the_sheet_a_person_fills_never_shows_the_judges_scores(tmp_path: Path) -> None:
    rows = [row("q1", "A", 4, 3, ("yes",)), row("q2", "A", 2, 1)]
    sheet, key = aggregate.write_human_sheet(rows, tmp_path)
    text = sheet.read_text()
    assert "judge_" not in text.splitlines()[0] and "human_faithfulness_1to5" in text
    assert [r["judge_faithfulness"] for r in csv.DictReader(key.open())] == ["4", "2"]


def test_kappa_is_one_for_perfect_agreement_and_low_for_disagreement() -> None:
    a = [1, 2, 3, 4, 5, 3, 3]
    assert aggregate.quadratic_weighted_kappa(a, a) == 1.0
    assert aggregate.quadratic_weighted_kappa([1, 1, 5, 5], [5, 5, 1, 1]) < 0
    # one item two steps off in an otherwise perfect list of eight
    h = [1, 2, 3, 4, 5, 1, 2, 3]
    j = [1, 2, 3, 4, 5, 1, 2, 5]
    assert 0.8 < aggregate.quadratic_weighted_kappa(h, j) < 1.0
    assert aggregate.quadratic_weighted_kappa([], []) is None
    # worked by hand with squared weights (absolute weights would give 0.686)
    got = aggregate.quadratic_weighted_kappa([1, 2, 3, 4, 5, 5, 1, 3], [1, 3, 3, 5, 4, 5, 2, 3])
    assert got == pytest.approx(0.875, abs=1e-3)


def test_agreement_with_a_filled_sheet_is_read_back(tmp_path: Path) -> None:
    rows = [row("q1", "A", 4, 3), row("q2", "A", 2, 5), row("q3", "A", 5, 5)]
    sheet, key = aggregate.write_human_sheet(rows, tmp_path)
    filled = list(csv.DictReader(sheet.open()))
    filled[0]["human_faithfulness_1to5"], filled[0]["human_relevance_1to5"] = "5", "3"  # judge 4/3
    filled[1]["human_faithfulness_1to5"] = "2"  # judge 2; relevance left blank
    filled[2]["human_faithfulness_1to5"], filled[2]["human_relevance_1to5"] = (
        "x",
        "4",
    )  # junk ignored
    with sheet.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=filled[0].keys())
        w.writeheader()
        w.writerows(filled)
    got = aggregate.read_filled_sheet(sheet, key)
    assert got["faithfulness"]["n"] == 2 and got["faithfulness"]["exact"] == 0.5
    assert got["faithfulness"]["within_1"] == 1.0 and got["faithfulness"]["mean_abs_error"] == 0.5
    assert got["relevance"]["n"] == 2 and got["relevance"]["mean_abs_error"] == 0.5  # |3-3|, |4-5|


def test_the_rubric_form_round_trips_and_means_ignore_blank_rows(tmp_path: Path) -> None:
    form = aggregate.write_rubric_form(
        [
            {"incident_id": "1", "title": "t", "summary": "s"},
            {"incident_id": "2", "title": "u", "summary": "v"},
        ],
        tmp_path / "form.csv",
    )
    rows = list(csv.DictReader(form.open()))
    rows[0].update(
        {
            "human_accuracy_1to5": "4",
            "human_completeness_1to5": "5",
            "human_causality_1to5": "3",
            "human_actionability_1to5": "2",
        }
    )
    with form.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    means = aggregate.read_filled_rubric(form)
    assert means["accuracy"]["mean"] == 4.0 and means["actionability"]["n"] == 1


def test_the_results_page_renders_for_two_runs_and_without_human_scores() -> None:
    rows = [row("a", "count", 5, 5, ("yes",)), row("b", "search", 3, 3)]
    reports = [
        {
            "incident_id": "1",
            "check": {
                "has_report": True,
                "valid": True,
                "cited": 1,
                "cited_not_in_index": 0,
                "cited_not_in_bundle": 0,
                "claims_left_out": 0,
            },
            "judgement": {"accuracy": 4, "completeness": 4, "causality": 4, "actionability": 4},
        }
    ]
    summary = {
        "answers": aggregate.summarise_answers(rows),
        "reports": aggregate.summarise_reports(reports),
    }
    text = run.markdown({"baseline": summary, "after": summary}, "2026-10-07", None)
    assert (
        "| | baseline | after |" in text
        and "Not measured yet" in text
        and "### By category (after)" in text
    )
    assert "llama3.2:3b" in text


def test_the_dumped_rows_round_trip(tmp_path: Path) -> None:
    run.dump(tmp_path / "x.jsonl", [{"a": 1}, {"b": [2, 3]}])
    assert run.load(tmp_path / "x.jsonl") == [{"a": 1}, {"b": [2, 3]}]
    assert run.load(tmp_path / "missing.jsonl") == []
    assert json.loads((tmp_path / "x.jsonl").read_text().splitlines()[1]) == {"b": [2, 3]}
