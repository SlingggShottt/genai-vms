"""Event listing rules — no I/O (design_architecture.md §9, `GET /events`).

The list is newest first by the event's own start, with ties broken by id, so a page boundary
falls the same way however many events share a start. The cursor is the last row of the page
(`<start>|<id>`); it is opaque to clients.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

CURSOR_SEPARATOR = "|"


class MalformedCursorError(ValueError):
    """The cursor is not one this API made."""


@dataclass(frozen=True)
class EventCursor:
    start_ts: datetime
    event_id: uuid.UUID

    def encode(self) -> str:
        return f"{self.start_ts.astimezone(UTC).isoformat()}{CURSOR_SEPARATOR}{self.event_id}"

    @classmethod
    def decode(cls, value: str) -> EventCursor:
        stamp, sep, ident = value.partition(CURSOR_SEPARATOR)
        if not sep:
            raise MalformedCursorError("cursor has no separator")
        try:
            start = datetime.fromisoformat(stamp)
            event_id = uuid.UUID(ident)
        except ValueError as exc:
            raise MalformedCursorError(str(exc)) from exc
        if start.tzinfo is None:
            raise MalformedCursorError("cursor time has no timezone")
        return cls(start.astimezone(UTC), event_id)
