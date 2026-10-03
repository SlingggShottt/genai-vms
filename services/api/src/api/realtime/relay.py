"""Redis pub/sub fan-out between api replicas (P3-J3: "works with 2 API replicas").

Whoever produces a message — the alerts consumer in whichever replica holds the Kafka
partition, an ack/resolve request on any replica — *publishes* it to one Redis channel; every
replica runs `run()`, which listens to that channel and hands what it hears to its own
`ConnectionHub`. A message therefore reaches every connected client exactly once, wherever
the client is connected, and the producer does not need to know where that is.

Pub/sub is fire-and-forget: a message published while a replica is reconnecting is lost to
that replica's clients. That is acceptable for a UI push — a client that missed something
refetches `GET /alerts` — and `run()` reconnects with backoff so the gap is short.
"""

from __future__ import annotations

import asyncio

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from vms_common.logging import get_logger

from api.cancellation import raise_if_cancelling
from api.realtime.hub import ConnectionHub
from api.realtime.messages import WsMessage

log = get_logger(__name__)

CHANNEL = "vms:ws:broadcast"
RECONNECT_BACKOFF_S = (0.5, 1.0, 2.0, 5.0)


class RedisRelay:
    def __init__(self, client: Redis, hub: ConnectionHub, *, channel: str = CHANNEL) -> None:
        self._client = client
        self._hub = hub
        self._channel = channel
        # Set while subscribed. A message published before this is set can be missed by this
        # replica (pub/sub keeps nothing), which matters to tests and to anything that wants
        # to know the live channel is up.
        self.ready = asyncio.Event()

    async def publish(self, message: WsMessage) -> None:
        """Send `message` to every replica. Raises `RedisError` if Redis is unreachable."""
        await self._client.publish(self._channel, message.to_json())

    async def run(self) -> None:
        """Listen forever, reconnecting on failure. Cancel to stop."""
        attempt = 0
        while True:
            try:
                async with self._client.pubsub() as pubsub:
                    await pubsub.subscribe(self._channel)
                    attempt = 0
                    self.ready.set()
                    log.info("ws_relay_subscribed", channel=self._channel)
                    while True:
                        # redis-py can lose a cancel that lands mid-connect; this notices it
                        # within one `get_message` timeout instead of listening for ever.
                        raise_if_cancelling()
                        raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        if raw is not None:
                            self._deliver(raw["data"])
            except (RedisError, OSError) as exc:
                # A cancel that surfaces as a Redis error while the subscription unwinds is
                # still a cancel (see api.cancellation) — not a connection to re-establish.
                raise_if_cancelling(exc)
                self.ready.clear()
                delay = RECONNECT_BACKOFF_S[min(attempt, len(RECONNECT_BACKOFF_S) - 1)]
                attempt += 1
                log.warning("ws_relay_disconnected", error=type(exc).__name__, retry_in_s=delay)
                await asyncio.sleep(delay)

    def _deliver(self, data: str | bytes) -> None:
        try:
            message = WsMessage.model_validate_json(data)
        except ValidationError:
            log.warning("ws_relay_bad_message")  # never echo the payload: it may hold alert text
            return
        self._hub.broadcast(message)
