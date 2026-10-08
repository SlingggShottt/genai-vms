"""Scripted assistant conversations (P6-D2) and conversation memory (P6-D3).

Twenty questions go through the router (the lookup a recognised question gets, with the arguments it
names); more are left to the model. Seven whole turns run through `Assistant.respond` with a
scripted model, a fake lookup and an in-memory store: events in order, the lookup's own sentence
first, citations resolved server-side from the tags the tools handed out, a tag nobody handed out
reported as unknown, a repeated lookup stopped, the model being down. The memory tests: the last
twelve messages verbatim, older ones folded into a summary, tool output cut to a budget. No network,
no database, no real model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from retrieval.assistant import agent as agent_module
from retrieval.assistant.agent import EVIDENCE_CHARS, RESULT_CHARS, Assistant
from retrieval.assistant.router import route
from retrieval.assistant.store import WINDOW, render_history, split_history
from retrieval.assistant.tools import Tool
from vms_common.llm.errors import LLMUnavailableError
from vms_common.llm.testing import FakeGateway

CAMERAS = ["bus-g331", "bus-g340", "cam01", "cam-2"]
TODAY = date(2026, 10, 7)

# (question, tool, arguments the lookup must carry)
ROUTED = [
    ("What happened today?", "list_events", {"when": "today"}),
    ("Show me the events from yesterday", "list_events", {"when": "yesterday"}),
    ("List the verified events on cam01", "list_events", {"camera": "cam01"}),
    ("Which events happened on bus-g340 on 2026-10-06?", "list_events",
     {"camera": "bus-g340", "when": "2026-10-06"}),
    ("Any intrusion events on 4 October?", "list_events",
     {"type": "intrusion", "when": "2026-10-04"}),
    ("How many verified events were there on bus-g331 on 6 October?", "list_events",
     {"camera": "bus-g331", "when": "2026-10-06"}),
    ("How many abandoned object events on the 4th of October?", "list_events",
     {"type": "abandoned_object", "when": "2026-10-04"}),
    ("How many people were on cam01 today?", "count_objects",
     {"category": "person", "camera": "cam01", "when": "today"}),
    ("How many cars were on bus-g340 on October 4?", "count_objects",
     {"category": "car", "camera": "bus-g340", "when": "2026-10-04"}),
    ("How many trucks yesterday?", "count_objects", {"category": "truck", "when": "yesterday"}),
    ("How many buses on cam-2 this week?", "count_objects", {"category": "bus", "camera": "cam-2"}),
    ("List the incidents", "list_incidents", {}),
    ("Any high severity incidents on bus-g331?", "list_incidents", {"camera": "bus-g331"}),
    ("Show me the incidents from yesterday", "list_incidents", {"when": "yesterday"}),
    ("Give me the daily report for yesterday", "get_daily_report", {"date": "yesterday"}),
    ("Daily report for 2026-10-05", "get_daily_report", {"date": "2026-10-05"}),
    ("What was the daily security report today?", "get_daily_report", {"date": "today"}),
    ("Show me footage of a person in a red jacket", "search_footage", {}),
    ("Find a white car near the gate", "search_footage", {}),
    ("Timeline for cam01 yesterday", "get_timeline", {"cameras": ["cam01"]}),
]  # fmt: skip


@pytest.mark.parametrize("question,tool,args", ROUTED, ids=[r[0][:48] for r in ROUTED])
def test_a_recognised_question_gets_the_right_lookup(question, tool, args) -> None:
    routed = route(question, CAMERAS, today=TODAY)
    assert routed is not None, f"{question!r} was not routed"
    got_tool, got_args = routed
    assert got_tool == tool
    for key, value in args.items():
        assert got_args.get(key) == value, (key, got_args)


@pytest.mark.parametrize(
    "question",
    [
        "What can you do?",
        "Hello",
        "Thanks, that is all",
        "What should I look at first this morning?",
        "Is anything unusual going on?",
        "Explain the severity levels",
    ],
)
def test_questions_that_name_no_lookup_are_left_to_the_model(question: str) -> None:
    assert route(question, CAMERAS, today=TODAY) is None


# ---- whole turns ---------------------------------------------------------------------------


@dataclass
class Row:
    role: str
    content: str
    status: str = "complete"


@dataclass
class FakeStore:
    rows: list[Row] = field(default_factory=list)
    saved: list[dict] = field(default_factory=list)
    title: str | None = None

    def _sessions(self):
        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def get(self, model, key):
                return None

        return _Session()

    async def messages(self, session_id):
        return list(self.rows)

    async def add(
        self, session_id, role, content, *, citations=None, tools=None, status="complete"
    ):
        self.rows.append(Row(role, content, status))
        if role == "assistant":
            self.saved.append({"content": content, "citations": citations, "status": status})
        return uuid.uuid4()

    async def set_title(self, session_id, title):
        self.title = title

    async def set_summary(self, *a, **k):
        return None


EVENT_LINES = (
    "2 verified event(s) (severity: 1 HIGH, 1 MEDIUM), newest first:\n"
    "{a} event: intrusion, severity HIGH, camera bus-g340, 06 Oct 21:59:10.\n"
    "{b} event: loitering, severity MEDIUM, camera bus-g331, 06 Oct 21:57:17.\n"
)


def fake_tool(text_for):
    """The real `list_events` tool with its lookup replaced: it hands out evidence tags the way the
    real one does and returns canned text."""

    async def run(ctx, args):
        tags = [
            ctx.evidence.event(
                "84912e49-0000-0000-0000-000000000000",
                "intrusion on bus-g340",
                camera="bus-g340",
                ts="2026-10-06T16:29:10+00:00",
            ),
            ctx.evidence.event(
                "b10e1385-0000-0000-0000-000000000000",
                "loitering on bus-g331",
                camera="bus-g331",
                ts="2026-10-06T16:27:17+00:00",
            ),
        ]
        return text_for.format(a=tags[0], b=tags[1])

    real = agent_module.TOOLS["list_events"]
    return Tool(real.name, real.description, real.args, run)


async def turn(monkeypatch, gateway, question, *, tool_text=EVENT_LINES, store=None):
    monkeypatch.setitem(agent_module.TOOLS, "list_events", fake_tool(tool_text))
    store = store or FakeStore()
    assistant = Assistant(
        gateway=gateway,
        store=store,
        ctx_factory=lambda evidence: SimpleNamespace(evidence=evidence),
        tz=ZoneInfo("Asia/Kolkata"),
        cameras=CAMERAS,
    )
    events = [e async for e in assistant.respond(uuid.uuid4(), question)]
    return events, store


def kinds(events):
    return [e["type"] for e in events]


async def test_a_turn_streams_the_lookup_first_then_the_answer_and_resolves_its_citations(
    monkeypatch,
) -> None:
    gateway = FakeGateway(
        {"assistant": "An intrusion on bus-g340 [E:84912e49] and loitering [E:b10e1385]."}
    )
    events, store = await turn(
        monkeypatch, gateway, "Which events happened on bus-g340 on 2026-10-06?"
    )

    assert kinds(events)[0] == "tool_call" and events[0]["tool"] == "list_events"
    assert kinds(events)[1] == "tool_result" and len(events[1]["cites"]) == 2
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert tokens[0].startswith("2 verified event(s)")  # the lookup's own words come first
    assert kinds(events)[-2:] == ["citation", "done"]
    cite = events[-2]
    assert [c["tag"] for c in cite["citations"]] == ["84912e49", "b10e1385"]
    assert cite["unknown"] == [] and cite["consulted"] is False
    assert store.saved[0]["status"] == "complete" and "[E:84912e49]" in store.saved[0]["content"]


async def test_a_tag_nobody_handed_out_is_reported_not_cited(monkeypatch) -> None:
    gateway = FakeGateway({"assistant": "It was an intrusion [E:deadbeef] on bus-g340."})
    events, _ = await turn(monkeypatch, gateway, "Which events happened on bus-g340 on 2026-10-06?")

    cite = next(e for e in events if e["type"] == "citation")
    assert cite["unknown"] == ["E:deadbeef"]
    # nothing the model wrote resolves, so what the lookup found is shown as "consulted"
    assert cite["consulted"] is True and all(c["consulted"] for c in cite["citations"])
    assert {c["tag"] for c in cite["citations"]} == {"84912e49", "b10e1385"}


async def test_an_answer_with_no_tags_shows_the_records_as_consulted(monkeypatch) -> None:
    gateway = FakeGateway({"assistant": "Both events are on the two bus cameras."})
    events, _ = await turn(monkeypatch, gateway, "Which events happened on bus-g340 on 2026-10-06?")
    cite = next(e for e in events if e["type"] == "citation")
    assert cite["consulted"] is True and cite["unknown"] == []


async def test_a_question_the_router_does_not_know_is_planned_by_the_model(monkeypatch) -> None:
    gateway = FakeGateway(
        {
            "assistant": [
                {"thought": "need the events", "action": "tool", "tool": "list_events",
                 "arguments": {"camera": "bus-g340"}},
                {"thought": "enough", "action": "answer"},
                "An intrusion on bus-g340 [E:84912e49].",
            ]
        }
    )  # fmt: skip
    events, store = await turn(monkeypatch, gateway, "What should I look at first this morning?")

    assert kinds(events).count("tool_call") == 1
    assert events[0]["arguments"]["camera"] == "bus-g340"
    assert [c["tag"] for c in next(e for e in events if e["type"] == "citation")["citations"]] == [
        "84912e49"
    ]
    assert store.title == "What should I look at first this morning?"


async def test_a_model_that_is_down_ends_the_turn_with_an_error_and_a_stored_failure(
    monkeypatch,
) -> None:
    gateway = FakeGateway({"assistant": [LLMUnavailableError("ollama is not running")]})
    events, store = await turn(
        monkeypatch, gateway, "Which events happened on bus-g340 on 2026-10-06?"
    )

    assert kinds(events)[-1] == "error" and "not available" in events[-1]["message"]
    assert "done" not in kinds(events) and "citation" not in kinds(events)
    assert kinds(events)[:2] == [
        "tool_call",
        "tool_result",
    ]  # what the lookup found was still shown
    assert store.saved[0]["status"] == "failed"


async def test_a_model_that_asks_for_the_same_lookup_twice_is_stopped_and_answers(
    monkeypatch,
) -> None:
    same = {
        "thought": "events",
        "action": "tool",
        "tool": "list_events",
        "arguments": {"camera": "bus-g340"},
    }
    gateway = FakeGateway({"assistant": [same, same, "An intrusion on bus-g340 [E:84912e49]."]})
    events, store = await turn(monkeypatch, gateway, "What should I look at first this morning?")

    assert kinds(events).count("tool_call") == 1  # the repeat was not run
    assert kinds(events)[-2:] == ["citation", "done"] and store.saved[0]["status"] == "complete"


# ---- conversation memory (P6-D3) --------------------------------------------------


def msgs(n: int) -> list[Row]:
    return [Row("user" if i % 2 == 0 else "assistant", f"message {i}") for i in range(n)]


def test_only_the_last_twelve_messages_stay_verbatim() -> None:
    assert WINDOW == 12
    older, recent = split_history(msgs(5))
    assert older == [] and [m.content for m in recent] == [f"message {i}" for i in range(5)]
    older, recent = split_history(msgs(15))
    assert [m.content for m in older] == ["message 0", "message 1", "message 2"]
    assert [m.content for m in recent] == [f"message {i}" for i in range(3, 15)]
    assert split_history(msgs(12)) == ([], msgs(12))


def test_history_is_rendered_with_roles_and_each_message_is_cut() -> None:
    rows = [Row("user", "x" * 900), Row("assistant", "short"), Row("assistant", "no", "failed")]
    text = render_history(rows)
    lines = text.splitlines()
    assert lines[0] == "Operator: " + "x" * 500 and lines[1] == "Assistant: short"
    assert len(lines) == 2  # a failed turn is not shown to the model again


class _SummaryStore(FakeStore):
    def __init__(self, rows, summary=None, covered=0):
        super().__init__(rows)
        self.row = SimpleNamespace(summary=summary, summarized_count=covered)
        self.summaries = []

    def _sessions(self):
        row = self.row

        class _S:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def get(self, model, key):
                return row

        return _S()

    async def set_summary(self, session_id, summary, covered):
        self.summaries.append((summary, covered))


def _assistant(store, gateway):
    return Assistant(
        gateway=gateway,
        store=store,
        ctx_factory=lambda evidence: SimpleNamespace(evidence=evidence),
        tz=ZoneInfo("Asia/Kolkata"),
        cameras=CAMERAS,
    )


async def test_messages_that_fell_out_of_the_window_are_folded_into_the_summary() -> None:
    store = _SummaryStore(msgs(15), summary="Earlier: asked about cam01.", covered=1)
    gateway = FakeGateway({"assistant": "Asked about cam01 and the plaza; nothing found."})

    await _assistant(store, gateway)._update_summary(uuid.uuid4())

    assert store.summaries == [("Asked about cam01 and the plaza; nothing found.", 3)]
    prompt = gateway.calls_for("assistant")[0].messages[0].content
    assert "Earlier: asked about cam01." in prompt  # the summary so far is carried forward
    assert "message 1" in prompt and "message 2" in prompt  # only what is new to it...
    assert (
        "message 0" not in prompt and "message 5" not in prompt
    )  # ...not what it covered, nor the window


async def test_nothing_is_summarised_until_something_falls_out_of_the_window() -> None:
    store = _SummaryStore(msgs(12))
    gateway = FakeGateway({"assistant": "never asked"})
    await _assistant(store, gateway)._update_summary(uuid.uuid4())
    assert store.summaries == [] and gateway.calls_for("assistant") == []

    store = _SummaryStore(msgs(15), summary="s", covered=3)  # already covers all three
    await _assistant(store, gateway)._update_summary(uuid.uuid4())
    assert store.summaries == [] and gateway.calls_for("assistant") == []


async def test_a_failing_summary_is_an_optimisation_lost_not_an_error() -> None:
    from vms_common.llm.errors import LLMUnavailableError

    store = _SummaryStore(msgs(15))
    gateway = FakeGateway({"assistant": [LLMUnavailableError("down")]})
    await _assistant(store, gateway)._update_summary(uuid.uuid4())  # does not raise
    assert store.summaries == []


async def test_a_long_tool_result_is_cut_before_the_model_sees_it(monkeypatch) -> None:
    huge = "5 verified event(s):\n" + "\n".join(
        f"{{a}} event number {i} " + "y" * 200 for i in range(200)
    )
    gateway = FakeGateway({"assistant": "Many events."})

    events, _ = await turn(
        monkeypatch, gateway, "Which events happened on bus-g340 on 2026-10-06?", tool_text=huge
    )

    prompt = gateway.calls_for("assistant")[0].messages[0].content
    assert "event number 0 " in prompt and "event number 199" not in prompt  # cut, not summarised
    assert prompt.count("event number") <= RESULT_CHARS // 200 + 1  # one result: RESULT_CHARS
    assert (
        len(prompt) < EVIDENCE_CHARS + 6000
    )  # the prompt's own text plus a bounded evidence block
    shown = next(e for e in events if e["type"] == "tool_result")["lines"]
    assert len(shown) <= 8 and all(len(line) <= 300 for line in shown)  # and so is what is streamed
    assert len(huge) > RESULT_CHARS
    assert kinds(events)[-1] == "done"


async def test_a_second_turn_sees_the_first_in_its_prompt(monkeypatch) -> None:
    store = FakeStore(
        [Row("user", "Which events were on bus-g340?"), Row("assistant", "Two events.")]
    )
    gateway = FakeGateway({"assistant": "On cam01 there were none."})

    await turn(monkeypatch, gateway, "And on cam01?", store=store)

    prompt = gateway.calls_for("assistant")[0].messages[0].content
    assert (
        "Operator: Which events were on bus-g340?" in prompt and "Assistant: Two events." in prompt
    )
