"""The event list's cursor (design_architecture.md §9, `GET /events`): what a page boundary is."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from api.domain.events import EventCursor, MalformedCursorError

NOON = datetime(2026, 10, 5, 12, 0, 0, 500_000, tzinfo=UTC)
ID = uuid.UUID("0197b1f2-8f3c-7a10-9b4e-1c2d3e4f5a6b")


def test_a_cursor_round_trips_to_the_same_row() -> None:
    cursor = EventCursor(NOON, ID)
    assert EventCursor.decode(cursor.encode()) == cursor


def test_a_cursor_is_written_in_utc_and_a_time_in_another_zone_reads_as_the_same_instant() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    assert EventCursor(NOON.astimezone(ist), ID).encode() == EventCursor(NOON, ID).encode()
    decoded = EventCursor.decode(f"{NOON.astimezone(ist).isoformat()}|{ID}")
    assert decoded.start_ts == NOON and decoded.start_ts.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-cursor",
        f"2026-10-05T12:00:00|{ID}",  # no timezone: ambiguous, so refused
        f"yesterday|{ID}",
        "2026-10-05T12:00:00+00:00|not-a-uuid",
        f"{NOON.isoformat()}|",
    ],
)
def test_a_cursor_this_api_did_not_make_is_refused(value: str) -> None:
    with pytest.raises(MalformedCursorError):
        EventCursor.decode(value)
