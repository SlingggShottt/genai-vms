"""Intent routing for the assistant's first tool call. Pure.

A 3B model plans tool calls unreliably (it skips them, or answers from nothing), so questions
that clearly mean one lookup are routed by keywords and only questions nobody recognises go to
the model's planner. The router never answers anything; it only chooses what to look up."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from retrieval.domain.plan import categories_in, event_hints_in, find_date

_COUNT = re.compile(r"\bhow many\b|\bnumber of\b|\bcount\b|\bpeak\b|\bbusiest\b|\bcrowded\b")
_DAILY = re.compile(
    r"\bdaily (?:\w+ )?report\b|\breport for\b|\bsummary of (the |yesterday|today)"
)  # "daily security report" too
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


def _when(q: str, today: date) -> str:
    named = find_date(q, today)
    if named is not None:  # "on 4 October" -> the day, in a form every tool understands
        return named.isoformat()
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


def _without_camera(q: str, camera: str | None) -> str:
    """`q` with the camera's code (written with or without its hyphens) taken out."""
    if not camera:
        return q
    parts = [re.escape(p) for p in re.split(r"[-_ ]", camera.lower()) if p]
    return re.sub(r"[-_ ]?".join(parts), " ", q)


def route(
    question: str, cameras: list[str], today: date | None = None
) -> tuple[str, dict[str, Any]] | None:
    """(tool, arguments) for a question that clearly means one lookup, else None. `today` is the
    site's date, needed to place a day written without a year."""
    q = question.lower()
    today = today or datetime.now(UTC).date()
    when = _when(q, today)
    camera = _camera(question, cameras)
    # A camera called "bus-g340" is not a question about buses.
    words = _without_camera(q, camera)

    if _DAILY.search(q):
        named = find_date(q, today)
        return "get_daily_report", {
            "date": named.isoformat() if named else "yesterday" if "yesterday" in q else "today"
        }
    # "how many" is a count of things seen, unless it is a count of events or incidents: those are
    # in the list's own header, and the person counter would answer a different question.
    counts_records = (_EVENT.search(q) or _INCIDENT.search(q)) and not categories_in(words)
    if _COUNT.search(q) and not counts_records:
        cats = categories_in(words) or ["person"]
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
        args = {"when": when, "limit": 5}
        if camera:
            args["camera"] = camera
        return "list_incidents", args
    if _EVENT.search(q):
        args = {"when": when, "limit": 10}
        hints = event_hints_in(q)
        if hints:
            args["type"] = hints[0]
        if camera:
            args["camera"] = camera
        return "list_events", args
    if _FIND.search(q) or categories_in(words):
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
