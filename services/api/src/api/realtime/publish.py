"""Best-effort pushes. A WebSocket message is a hint that something changed — the state itself
is in Postgres — so failing to push (Redis briefly down) must never fail the request or the
consumer that caused it: it is logged and counted, and a client that missed it refetches."""

from __future__ import annotations

from redis.exceptions import RedisError
from vms_common.logging import get_logger

from api.metrics import ws_publish_errors_total
from api.realtime.messages import WsMessage
from api.realtime.relay import RedisRelay

log = get_logger(__name__)


async def publish_best_effort(relay: RedisRelay, message: WsMessage) -> bool:
    try:
        await relay.publish(message)
    except (RedisError, OSError) as exc:
        ws_publish_errors_total.inc()
        log.warning("ws_publish_failed", message_type=message.type, error=type(exc).__name__)
        return False
    return True
