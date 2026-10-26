"""`queries.jsonl`: the questions the retrieval benchmark asks, and what a good answer is (P4-J6).

One JSON object per line:

    {"id": "q001", "query": "a person gets into a car", "kind": "explicit",
     "label": "enter-vehicle", "filters": {"cameras": ["meva-ex"]},
     "relevant": [{"camera": "meva-ex", "start_s": 12.0, "end_s": 19.5}], "note": ""}

* `kind`: `explicit` names what happens the way the label does; `implicit` describes it without
  the label's words ("someone rises from their seat" for `stand-up`). The split matters: search
  that only matches words looks fine on explicit queries. The check is mechanical, not a judgement
  (`mentions_label`), so a reviewer does not have to decide it.
* `relevant`: where the answer is. `start_s`/`end_s` are seconds on the recording's own clock
  (the benchmark finds when that clock started), or `start`/`end` are absolute ISO times with a
  zone. Every place the thing happens must be listed: a result that lands on an unlisted one
  counts as wrong.
* `filters`: the camera and time range the operator would also have given; used by the
  `embed+filters` and later configurations.
* `label`: what the ground truth calls it, so `implicit` can be checked.

`problems()` returns what is wrong with a file, in words; the runner refuses a file with any.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

KINDS = ("explicit", "implicit")
# words of a label that say nothing about what happened ("people-talking" -> people, talking)
LABEL_STOP = frozenset({"a", "an", "the", "of", "on", "in", "up", "down", "to", "through", "off"})
MAX_QUERY_CHARS = 500


@dataclass(frozen=True)
class Segment:
    camera: str
    start: float  # seconds: on the recording's clock if `relative`, else epoch seconds
    end: float
    relative: bool


@dataclass(frozen=True)
class Query:
    id: str
    text: str
    kind: str
    label: str | None
    cameras: tuple[str, ...]
    relevant: tuple[Segment, ...]
    note: str = ""
    errors: tuple[str, ...] = field(default=(), compare=False)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def label_words(label: str) -> set[str]:
    return {w for w in words(label.replace("-", " ").replace("_", " ")) if w not in LABEL_STOP}


def mentions_label(text: str, label: str) -> bool:
    """Whether the query uses any of the label's words (whole words, case-insensitive)."""
    return bool(label_words(label) & set(words(text)))


def _segment(raw: dict) -> tuple[Segment | None, str | None]:
    camera = raw.get("camera")
    if not isinstance(camera, str) or not camera:
        return None, "a relevant place has no camera"
    relative = "start_s" in raw or "end_s" in raw
    absolute = "start" in raw or "end" in raw
    if relative == absolute:
        return None, f"a relevant place on {camera} needs start_s/end_s or start/end, not both"
    try:
        if relative:
            start, end = float(raw["start_s"]), float(raw["end_s"])
        else:
            start = datetime.fromisoformat(raw["start"]).timestamp()
            end = datetime.fromisoformat(raw["end"]).timestamp()
            for key in ("start", "end"):
                if datetime.fromisoformat(raw[key]).tzinfo is None:
                    return None, f"{key} of a relevant place on {camera} has no time zone"
    except (KeyError, TypeError, ValueError):
        return None, f"a relevant place on {camera} has a start or end that cannot be read"
    if end <= start:
        return None, f"a relevant place on {camera} ends before it starts"
    return Segment(camera, start, end, relative), None


def parse(line: str) -> Query:
    """A line as a Query; whatever is wrong with it is in `errors` rather than raised, so one
    bad line does not hide the others."""
    errors: list[str] = []
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        return Query("?", "", "?", None, (), (), errors=(f"not JSON: {exc.msg}",))
    if not isinstance(raw, dict):
        return Query("?", "", "?", None, (), (), errors=("a line must be a JSON object",))
    segments = []
    for item in raw.get("relevant") or []:
        seg, err = (
            _segment(item)
            if isinstance(item, dict)
            else (None, "a relevant place is not an object")
        )
        if err:
            errors.append(err)
        elif seg:
            segments.append(seg)
    filters = raw.get("filters") or {}
    return Query(
        id=str(raw.get("id", "")),
        text=str(raw.get("query", "")),
        kind=str(raw.get("kind", "")),
        label=raw.get("label"),
        cameras=tuple(filters.get("cameras") or ()),
        relevant=tuple(segments),
        note=str(raw.get("note", "")),
        errors=tuple(errors),
    )


def load(path: Path) -> list[Query]:
    return [parse(line) for line in path.read_text().splitlines() if line.strip()]


def problems(queries: Iterable[Query]) -> list[str]:
    """Everything wrong with a set of queries, each as a sentence naming the query."""
    out: list[str] = []
    seen: set[str] = set()
    for i, q in enumerate(queries, start=1):
        name = q.id or f"line {i}"
        out += [f"{name}: {e}" for e in q.errors]
        if not q.id:
            out.append(f"{name}: no id")
        elif q.id in seen:
            out.append(f"{name}: id used twice")
        seen.add(q.id)
        if not 2 <= len(q.text) <= MAX_QUERY_CHARS:
            out.append(f"{name}: the query must be 2 to {MAX_QUERY_CHARS} characters")
        if q.kind not in KINDS:
            out.append(f"{name}: kind must be one of {', '.join(KINDS)}")
        if not q.relevant and not q.errors:
            out.append(f"{name}: no relevant place; a query with no answer scores nothing")
        if q.cameras:
            stray = sorted({s.camera for s in q.relevant} - set(q.cameras))
            if stray:
                out.append(f"{name}: relevant on {', '.join(stray)}, outside the camera filter")
        if q.kind == "implicit":
            if not q.label:
                out.append(f"{name}: an implicit query needs its label, so that can be checked")
            elif mentions_label(q.text, q.label):
                out.append(
                    f"{name}: an implicit query must not use the words of its label ({q.label})"
                )
    return out


def summary(queries: list[Query]) -> dict[str, int | float]:
    n = len(queries)
    implicit = sum(q.kind == "implicit" for q in queries)
    return {
        "queries": n,
        "implicit": implicit,
        "implicit_share": round(implicit / n, 3) if n else 0.0,
        "with_filters": sum(bool(q.cameras) for q in queries),
        "relevant_places": sum(len(q.relevant) for q in queries),
    }
