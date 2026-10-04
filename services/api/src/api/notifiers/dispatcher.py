"""Send one notice to every enabled channel, concurrently, and never let a channel's failure
out: a dead SMTP server must not stop the dashboard push, and none of it may fail the alert
that was already stored. Each channel gets `timeout_s`; the outcome is counted per channel."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from vms_common.logging import get_logger

from api.metrics import notifications_total
from api.notifiers.base import AlertNotice, Notifier

log = get_logger(__name__)


class NotificationDispatcher:
    def __init__(self, notifiers: Sequence[Notifier], *, timeout_s: float = 10.0) -> None:
        self._notifiers = list(notifiers)
        self._timeout_s = timeout_s

    @property
    def channels(self) -> list[str]:
        return [n.name for n in self._notifiers]

    async def dispatch(self, notice: AlertNotice) -> dict[str, str]:
        """Returns `{channel: "ok" | "error" | "timeout"}`. Cancellation still propagates."""
        if not self._notifiers:
            return {}
        outcomes = await asyncio.gather(*(self._send_one(n, notice) for n in self._notifiers))
        return dict(outcomes)

    async def _send_one(self, notifier: Notifier, notice: AlertNotice) -> tuple[str, str]:
        try:
            await asyncio.wait_for(notifier.send(notice), timeout=self._timeout_s)
        except TimeoutError:
            result = "timeout"
        except Exception as exc:  # noqa: BLE001 - isolation is the point; the type is logged
            result = "error"
            # The type and the notifier's own (already sanitised) message — never `repr(exc)`:
            # a library exception may carry a URL with a token in it.
            detail = str(exc) if exc.__class__.__name__ == "NotifierError" else ""
            log.warning(
                "notification_failed",
                channel=notifier.name,
                alert_id=notice.alert_id,
                error=type(exc).__name__,
                detail=detail,
            )
        else:
            result = "ok"
        if result == "timeout":
            log.warning("notification_timed_out", channel=notifier.name, alert_id=notice.alert_id)
        notifications_total.labels(channel=notifier.name, result=result).inc()
        return notifier.name, result
