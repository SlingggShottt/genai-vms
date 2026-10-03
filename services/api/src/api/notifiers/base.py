"""The notifier interface (P3-J3, FR-ALR-03): one `send` per channel, fed one `AlertNotice`.

A channel is a small class — `name` plus `async send(notice)` — so adding one (SMS, a webhook)
is a new module and a line in `registry.py`, not a change to the alert code. `send` raises on
failure; the dispatcher (`dispatcher.py`) is what keeps one broken channel from affecting the
others or the alert itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

# India has no daylight saving, so a fixed offset is exactly Asia/Kolkata — and needs no tzdata.
# Times are UTC everywhere in the system; IST appears only where a person reads it
# (CLAUDE.md: "IST only in UI/PDF formatting").
IST = timezone(timedelta(hours=5, minutes=30), "IST")

MAX_CAPTION_CHARS = 500


class NotifierError(Exception):
    """A channel could not deliver. The message must be safe to log: no URLs with tokens in
    them, no credentials."""


@dataclass(frozen=True)
class AlertNotice:
    """What a channel is told about a new alert."""

    alert_id: str
    title: str
    severity: str
    event_type: str
    camera_code: str
    caption: str | None
    start_ts: datetime
    # The alert as the API presents it (`AlertOut`, JSON mode, without presigned urls) — what
    # the dashboard channel pushes to browsers.
    payload: dict[str, Any]


class Notifier(Protocol):
    name: str

    async def send(self, notice: AlertNotice) -> None: ...


def subject_line(notice: AlertNotice) -> str:
    return " ".join(f"[{notice.severity.upper()}] {notice.title}".split())  # one line, always


def body_text(notice: AlertNotice) -> str:
    """Plain text on purpose: the caption is model-written, and plain text cannot carry markup
    into an email client or a chat."""
    when = notice.start_ts.astimezone(IST).strftime("%d %b %Y, %H:%M:%S IST")
    lines = [subject_line(notice), when]
    if notice.caption:
        caption = " ".join(notice.caption.split())
        if len(caption) > MAX_CAPTION_CHARS:
            caption = caption[: MAX_CAPTION_CHARS - 1].rstrip() + "…"
        lines += ["", caption]
    lines += ["", f"Alert {notice.alert_id}"]
    return "\n".join(lines)
