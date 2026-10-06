"""The evidence one assistant turn has gathered, and the short ids the model cites it by.

A 3B model cannot be trusted to copy a 36-character uuid or a segment id, so every piece of
evidence a tool returns gets an 8-character tag (`[E:30b6f125]`, `[I:01a105b2]`, `[S:7f3a9c21]`)
and the answer cites those. The tags are resolved here, server-side, to the real ids; a tag that
was never handed out is *not* a citation and the UI is told so. Pure."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

CITATION = re.compile(r"\[([EIS]):([0-9a-zA-Z_-]{4,40})\]")


@dataclass(frozen=True)
class Cite:
    kind: str  # E event | I incident | S footage
    tag: str
    ref: str  # event id / incident id / segment id
    label: str
    ts: str | None = None  # ISO time (S: where in the segment)
    camera: str | None = None

    def as_json(self) -> dict:
        return {
            "kind": self.kind,
            "tag": self.tag,
            "ref": self.ref,
            "label": self.label,
            "ts": self.ts,
            "camera": self.camera,
        }


@dataclass
class Evidence:
    _by_tag: dict[str, Cite] = field(default_factory=dict)

    def event(self, event_id: str, label: str, *, camera: str | None, ts: str | None) -> str:
        return self._add("E", event_id[:8], event_id, label, ts, camera)

    def incident(self, incident_id: str, label: str, *, ts: str | None = None) -> str:
        return self._add("I", incident_id[:8], incident_id, label, ts, None)

    def footage(self, segment_id: str, ts: str, label: str, *, camera: str | None) -> str:
        tag = hashlib.sha1(f"{segment_id}|{ts}".encode()).hexdigest()[:8]  # noqa: S324 - an id
        return self._add("S", tag, segment_id, label, ts, camera)

    def _add(self, kind, tag, ref, label, ts, camera) -> str:
        self._by_tag.setdefault(f"{kind}:{tag}", Cite(kind, tag, ref, label, ts, camera))
        return f"[{kind}:{tag}]"

    def resolve(self, text: str) -> tuple[list[Cite], list[str]]:
        """(valid citations in order of first use, tags that were never handed out)."""
        valid: dict[str, Cite] = {}
        unknown: list[str] = []
        for m in CITATION.finditer(text):
            key = f"{m.group(1)}:{m.group(2)}"
            cite = self._by_tag.get(key)
            if cite is None:
                if key not in unknown:
                    unknown.append(key)
            else:
                valid.setdefault(key, cite)
        return list(valid.values()), unknown

    def all(self) -> list[Cite]:
        """Everything the tools returned, in the order it was found."""
        return list(self._by_tag.values())

    def __len__(self) -> int:
        return len(self._by_tag)
