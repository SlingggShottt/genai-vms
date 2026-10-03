"""The connections of *this* api process (design_architecture.md §9: `WS /ws`).

`ConnectionHub` holds one bounded queue per connected socket. `broadcast` is synchronous and
never waits: it puts the message on the queue of every connection whose role may receive it, and a
connection that has fallen too far behind is dropped (it reconnects and refetches) rather than
having messages buffered without bound or slowing everyone else down. The socket's own task drains
its queue (`api/api/ws.py`).

Delivery across processes is `relay.py`: every replica subscribes to the same Redis channel and
feeds what it hears into its own hub.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field

from vms_common.logging import get_logger

from api.domain.alerts import role_may_receive
from api.metrics import ws_connections, ws_dropped_total, ws_messages_total
from api.realtime.messages import WsMessage

log = get_logger(__name__)


@dataclass
class Subscriber:
    id: int
    role: str
    queue: asyncio.Queue[str]
    overflowed: asyncio.Event = field(default_factory=asyncio.Event)  # set when dropped as too slow


class ConnectionHub:
    def __init__(self, *, queue_size: int = 100) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[int, Subscriber] = {}
        self._ids = itertools.count(1)

    @property
    def connection_count(self) -> int:
        return len(self._subscribers)

    def connect(self, role: str) -> Subscriber:
        subscriber = Subscriber(
            id=next(self._ids), role=role, queue=asyncio.Queue(maxsize=self._queue_size)
        )
        self._subscribers[subscriber.id] = subscriber
        ws_connections.set(len(self._subscribers))
        return subscriber

    def disconnect(self, subscriber: Subscriber) -> None:
        self._subscribers.pop(subscriber.id, None)
        ws_connections.set(len(self._subscribers))

    def broadcast(self, message: WsMessage) -> int:
        """Queue `message` for every connection whose role may receive it; returns how many."""
        payload = message.to_json()
        delivered = 0
        for subscriber in list(self._subscribers.values()):
            if subscriber.overflowed.is_set() or not role_may_receive(
                subscriber.role, message.type
            ):
                continue
            try:
                subscriber.queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Too far behind to catch up: stop buffering for it. The socket task sees the flag,
                # closes the connection, and the client reconnects and refetches.
                subscriber.overflowed.set()
                ws_dropped_total.inc()
                log.warning(
                    "ws_subscriber_dropped", role=subscriber.role, queued=subscriber.queue.qsize()
                )
                continue
            delivered += 1
            ws_messages_total.labels(type=message.type).inc()
        return delivered
