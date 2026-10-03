"""The Redis relay against a real Redis (P3-J3: "works with 2 API replicas"). Run via
`make test-int` (needs Docker)."""

from __future__ import annotations

import asyncio
import json

import pytest
from api.realtime.hub import ConnectionHub
from api.realtime.messages import WsMessage
from api.realtime.relay import CHANNEL, RedisRelay
from redis.exceptions import ConnectionError as RedisConnectionError

pytestmark = pytest.mark.integration


def msg(type_: str = "alert.created", **data: object) -> WsMessage:
    return WsMessage(type=type_, data=data or {"n": 1})


async def next_message(subscriber, timeout_s: float = 5.0) -> dict:
    return json.loads(await asyncio.wait_for(subscriber.queue.get(), timeout_s))


async def running(relay: RedisRelay) -> asyncio.Task:
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)  # let it subscribe before anything is published
    return task


async def stop(*tasks: asyncio.Task) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_a_published_message_reaches_the_local_hub(redis_client) -> None:
    hub = ConnectionHub()
    sub = hub.connect("operator")
    relay = RedisRelay(redis_client, hub)
    task = await running(relay)
    try:
        await relay.publish(msg("alert.created", id="a1"))
        assert (await next_message(sub))["data"] == {"id": "a1"}
    finally:
        await stop(task)


async def test_every_replica_hears_a_message_published_by_any_of_them(redis_client) -> None:
    hub_a, hub_b = ConnectionHub(), ConnectionHub()
    client_a, client_b = hub_a.connect("operator"), hub_b.connect("admin")
    relay_a, relay_b = RedisRelay(redis_client, hub_a), RedisRelay(redis_client, hub_b)
    tasks = [await running(relay_a), await running(relay_b)]
    try:
        await relay_a.publish(msg("alert.created", id="from-a"))  # produced on replica A...
        await relay_b.publish(msg("alert.updated", id="from-b"))  # ...and on replica B
        for client in (client_a, client_b):
            heard = {(await next_message(client))["data"]["id"] for _ in range(2)}
            assert heard == {"from-a", "from-b"}  # each client heard both
            assert client.queue.empty()  # exactly once
    finally:
        await stop(*tasks)


async def test_role_filtering_still_applies_after_the_relay(redis_client) -> None:
    hub = ConnectionHub()
    viewer, operator = hub.connect("viewer"), hub.connect("operator")
    relay = RedisRelay(redis_client, hub)
    task = await running(relay)
    try:
        await relay.publish(msg("alert.created"))
        await next_message(operator)
        assert viewer.queue.empty()
    finally:
        await stop(task)


async def test_garbage_on_the_channel_is_ignored_and_the_relay_carries_on(redis_client) -> None:
    hub = ConnectionHub()
    sub = hub.connect("operator")
    relay = RedisRelay(redis_client, hub)
    task = await running(relay)
    try:
        for junk in ("not json", '{"type": "alert.created"}', "[]", ""):
            await redis_client.publish(CHANNEL, junk)
        await relay.publish(msg("alert.created", id="real"))
        assert (await next_message(sub))["data"] == {"id": "real"}
        assert sub.queue.empty()  # none of the junk got through
    finally:
        await stop(task)


async def test_the_relay_reconnects_after_the_subscription_fails(redis_client, monkeypatch) -> None:
    hub = ConnectionHub()
    sub = hub.connect("operator")
    relay = RedisRelay(redis_client, hub)
    real_pubsub = redis_client.pubsub
    attempts = {"n": 0}

    def flaky_pubsub(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RedisConnectionError("redis went away")
        return real_pubsub(*args, **kwargs)

    monkeypatch.setattr(redis_client, "pubsub", flaky_pubsub)
    monkeypatch.setattr("api.realtime.relay.RECONNECT_BACKOFF_S", (0.05,))
    task = asyncio.create_task(relay.run())
    try:
        await asyncio.sleep(0.5)  # first attempt fails, the second subscribes
        assert attempts["n"] >= 2
        await relay.publish(msg("alert.created", id="after-outage"))
        assert (await next_message(sub))["data"] == {"id": "after-outage"}
    finally:
        await stop(task)


async def test_publishing_with_redis_down_raises_so_the_caller_can_decide() -> None:
    class Down:
        async def publish(self, *_a, **_k):
            raise RedisConnectionError("down")

    relay = RedisRelay(Down(), ConnectionHub())  # type: ignore[arg-type]
    with pytest.raises(RedisConnectionError):
        await relay.publish(msg())
