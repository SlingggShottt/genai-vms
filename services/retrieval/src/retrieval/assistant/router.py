"""Intent routing for the assistant's first tool call. Pure.

A 3B model plans tool calls unreliably (it skips them, or answers from nothing), so questions
that clearly mean one lookup are routed by keywords and only questions nobody recognises go to
the model's planner. The router never answers anything; it only chooses what to look up."""

from __future__ import annotations

import re
from typing import Any

from retrieval.domain.plan import categories_in, event_hints_in

_COUNT = re.compile(r"\bhow many\b|\bnumber of\b|\bcount\b|\bpeak\b|\bbusiest\b|\bcrowded\b")
_DAILY = re.compile(r"\bdaily report\b|\breport for\b|\bsummary of (the |yesterday|today)")
_INCIDENT = re.compile(r"\bincidents?\b|\bincident reports?\b")
_EVENT = re.compile(
    r"\bevents?\b|\balerts?\b|\bwhat happened\b|\bhappen(ed)?\b|\bserious\b|\bsuspicious\b|"
    r"\bintrusion|\bloiter|\bcrowding\b|\brunning\b|\babandoned\b|\bunattended\b"
)
_FIND = re.compile(
    r"\bfind\b|\bshow me\b|\bsearch\b|\blook(ing)? for\b|\blocate\b|\bspot\b|\banyone\b|"
    r"\bsomeone\b|\bwearing\b|\bcarrying\b|\bholding\b|\bwalking\b"
)
_TIMELINE = re.compile(r"\btimeline\b|\bin order\b|\bsequence\b")
_HOUR_WORDS = re.compile(r"\bbusiest\b|\bpeak\b|\bhour\b|\bwhen\b|\bwhat time\b")

DEFAULT_WHEN = "last 24 hours"


def _when(q: str) -> str:
    for phrase in (
        "yesterday",
        "today",
        "this morning",
        "this afternoon",
        "this evening",
        "tonight",
        "last night",
    ):
        if phrase in q:
            return phrase
    m = re.search(r"\b(?:last|past)\s+(\d+\s*(?:second|sec|minute|min|hour|hr|day)s?)\b", q)
    if m:
        return f"last {m.group(1)}"
    m = re.search(r"\b(?:last|past)\s+(hour|minute|day)\b", q)
    if m:
        return f"last {m.group(1)}"
    return DEFAULT_WHEN


def _camera(q: str, cameras: list[str]) -> str | None:
    low = q.lower().replace(" ", "")
    return next((c for c in cameras if c.lower().replace("-", "") in low.replace("-", "")), None)


def route(question: str, cameras: list[str]) -> tuple[str, dict[str, Any]] | None:
    """(tool, arguments) for a question that clearly means one lookup, else None."""
    q = question.lower()
    when = _when(q)
    camera = _camera(question, cameras)

    if _DAILY.search(q):
        day = "yesterday" if "yesterday" in q else "today"
        return "get_daily_report", {"date": day}
    if _COUNT.search(q):
        cats = categories_in(q) or ["person"]
        args: dict[str, Any] = {
            "category": cats[0],
            "when": when,
            "group_by": "hour" if _HOUR_WORDS.search(q) else "none",
        }
        if camera:
            args["camera"] = camera
        return "count_objects", args
    if _TIMELINE.search(q):
        return "get_timeline", {"when": when, **({"cameras": [camera]} if camera else {})}
    if _INCIDENT.search(q):
        return "list_incidents", {"when": when, "limit": 5}
    if _EVENT.search(q):
        args = {"when": when, "limit": 10}
        hints = event_hints_in(q)
        if hints:
            args["type"] = hints[0]
        if camera:
            args["camera"] = camera
        return "list_events", args
    if _FIND.search(q) or categories_in(q):
        return "search_footage", {
            "query": question.strip().rstrip("?"),
            "when": when if when != DEFAULT_WHEN else None,
            "cameras": [camera] if camera else [],
        }
    return None


def lead_sentence(tool: str, result: str) -> str | None:
    """A first sentence that is simply what the tool found, in its own words: the model
    continues from here and is told not to contradict it."""
    first = result.splitlines()[0].strip() if result else ""
    first = re.sub(r"\[[EIS]:[^\]]+\]\s*", "", first).rstrip(":").strip()
    if not first or first.lower().startswith(("error", "no ")):
        return first[:1].upper() + first[1:].rstrip(".") + "." if first else None
    if tool in ("list_events", "list_incidents", "get_timeline"):
        first = first.replace(", newest first", "").replace(", oldest first", "")
    return first[:1].upper() + first[1:].rstrip(".") + "."
