"""Pushing "something changed" to the browsers (design_architecture.md §9).

The reasoning worker publishes `job.progress` and `incident.ready` to the Redis channel the API's
WebSocket relay listens on, and the relay forwards them to the clients allowed to see them. A
message is a hint (the state is in Postgres), so a failure to send is counted and logged and never
fails a job: a client that missed one refetches.
"""

from __future__ import annotations

from typing import Protocol

from redis.exceptions import RedisError
from vms_common.contracts.ws import WS_CHANNEL, WsMessage
from vms_common.logging import get_logger

from reasoning.metrics import ws_publish_errors_total

log = get_logger(__name__)


class Notifier(Protocol):
    async def send(self, message: WsMessage) -> bool: ...


class RedisNotifier:
    def __init__(self, client, *, channel: str = WS_CHANNEL) -> None:  # noqa: ANN001
        self._client = client
        self._channel = channel

    async def send(self, message: WsMessage) -> bool:
        """True if it was published. Never raises for a Redis problem."""
        try:
            await self._client.publish(self._channel, message.to_json())
        except (RedisError, OSError) as exc:
            ws_publish_errors_total.inc()
            log.warning("ws_publish_failed", message_type=message.type, error=type(exc).__name__)
            return False
        return True
