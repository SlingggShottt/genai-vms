"""The dashboard channel: push `alert.created` to every connected browser (via the Redis
relay, so every api replica's clients get it)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from api.notifiers.base import AlertNotice
from api.realtime.messages import WsMessage


class DashboardNotifier:
    name = "dashboard"

    def __init__(self, publish: Callable[[WsMessage], Awaitable[None]]) -> None:
        self._publish = publish

    async def send(self, notice: AlertNotice) -> None:
        await self._publish(WsMessage(type="alert.created", data=notice.payload))
