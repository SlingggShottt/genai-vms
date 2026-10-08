"""Ask the assistant a list of questions through the real API and keep the transcripts.

Each question gets a fresh session (one turn, no memory from the others, so an answer does not
depend on the order of the list). A transcript holds what a judge needs to check the answer against
what the assistant actually had in front of it: the answer text, each lookup it made with the first
lines of what that lookup returned, and the records it cited.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

import httpx


@dataclass
class Transcript:
    qid: str
    category: str
    question: str
    answer: str = ""
    tools: list[dict] = field(default_factory=list)  # {tool, arguments, summary, lines}
    citations: list[dict] = field(default_factory=list)  # {tag, kind, label, camera, ts}
    consulted_only: bool = False  # the model cited nothing that resolved; these are what it read
    unknown_tags: list[str] = field(
        default_factory=list
    )  # tags written in the answer that match no record
    seconds: float = 0.0
    error: str = ""

    def as_json(self) -> dict:
        return asdict(self)


def parse_sse(raw: str) -> list[dict]:
    """The events of a server-sent-event stream, in order: `{"type", ...payload}`. A block with no
    `data:` line, or whose data is not JSON, is skipped (comments and keep-alives)."""
    events = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        data = "".join(line[5:].lstrip() for line in block.split("\n") if line.startswith("data:"))
        if not data:
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        name = next(
            (line[6:].strip() for line in block.split("\n") if line.startswith("event:")), None
        )
        if isinstance(payload, dict):
            events.append({"type": name or payload.get("type", ""), **payload})
    return events


def fold(qid: str, category: str, question: str, events: list[dict], seconds: float) -> Transcript:
    """One turn's events -> a transcript."""
    t = Transcript(qid, category, question, seconds=round(seconds, 2))
    answer: list[str] = []
    asked: dict = {}
    for e in events:
        kind = e.get("type")
        if kind == "token":
            answer.append(e.get("text", ""))
        elif kind == "tool_call":
            asked = e.get("arguments") or {}
        elif kind == "tool_result":
            t.tools.append(
                {k: e.get(k) for k in ("tool", "summary", "lines")}
                | {"arguments": asked, "cites": e.get("cites", [])}
            )
            asked = {}
        elif kind == "citation":
            t.citations = e.get("citations", [])
            t.consulted_only = bool(e.get("consulted"))
            t.unknown_tags = list(e.get("unknown", []))
        elif kind == "error":
            t.error = e.get("message", "error")
    t.answer = "".join(answer).strip()
    return t


class Assistant:
    """The API's assistant endpoints, logged in as an operator or admin."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        *,
        timeout: float = 300.0,
        max_waits: int = 6,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.max_waits = max_waits
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        r = self._http.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        self._http.headers["Authorization"] = "Bearer " + r.json()["access_token"]

    def _post_with_patience(self, url: str, **kw) -> httpx.Response:
        """POST, waiting out the API's rate limit (429 + Retry-After) rather than failing."""
        for _ in range(self.max_waits + 1):
            r = self._http.post(url, **kw)
            if r.status_code != 429:
                return r
            time.sleep(min(float(r.headers.get("Retry-After", "5")), 90.0) + 0.5)
        return r

    def ask(self, qid: str, category: str, question: str) -> Transcript:
        started = time.perf_counter()
        try:
            session = self._post_with_patience("/assistant/sessions")
            session.raise_for_status()
            sid = session.json()["id"]
            for _ in range(self.max_waits + 1):
                with self._http.stream(
                    "POST", f"/assistant/sessions/{sid}/messages", json={"content": question}
                ) as r:
                    if r.status_code == 429:
                        wait = float(r.headers.get("Retry-After", "5"))
                    else:
                        r.raise_for_status()
                        raw = "".join(r.iter_text())
                        break
                time.sleep(min(wait, 90.0) + 0.5)
            else:
                raise httpx.HTTPError("still rate limited after waiting")
            events = parse_sse(raw)
            self._http.delete(f"/assistant/sessions/{sid}")
        except httpx.HTTPError as exc:
            t = Transcript(qid, category, question, seconds=round(time.perf_counter() - started, 2))
            t.error = f"{type(exc).__name__}: {exc}"[:200]
            return t
        return fold(qid, category, question, events, time.perf_counter() - started)

    def close(self) -> None:
        self._http.close()
