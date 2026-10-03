"""A cancelled loop must stop even when a library loses or rewrites the cancellation
(P3-J3 — found as an app shutdown that hung against real Redis)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from api.cancellation import raise_if_cancelling
from api.realtime.hub import ConnectionHub
from api.realtime.relay import RedisRelay
from redis.exceptions import ConnectionError as RedisConnectionError


async def finishes(task: asyncio.Task, within_s: float = 3.0) -> bool:
    done, _pending = await asyncio.wait({task}, timeout=within_s)
    return bool(done)


# --- the helper ----------------------------------------------------------------------------------


async def test_nothing_is_raised_when_nobody_cancelled() -> None:
    raise_if_cancelling()
    raise_if_cancelling(RuntimeError("x"))


async def test_a_swallowed_cancellation_is_still_noticed() -> None:
    noticed = asyncio.Event()

    async def library_that_eats_cancels() -> None:
        with contextlib.suppress(asyncio.CancelledError):  # what redis-py does mid-connect
            await asyncio.sleep(3600)

    async def loop() -> None:
        await library_that_eats_cancels()
        try:
            raise_if_cancelling()
        except asyncio.CancelledError:
            noticed.set()
            raise

    task = asyncio.create_task(loop())
    await asyncio.sleep(0.01)
    task.cancel()
    assert await finishes(task)
    assert noticed.is_set() and task.cancelled()


async def test_the_replacing_error_is_kept_as_the_cause() -> None:
    cause = RedisConnectionError("closing")
    seen: list[BaseException | None] = []

    async def loop() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            try:
                raise cause  # the library raises its own error while unwinding
            except RedisConnectionError as exc:
                try:
                    raise_if_cancelling(exc)
                except asyncio.CancelledError as cancelled:
                    seen.append(cancelled.__cause__)
                    raise

    task = asyncio.create_task(loop())
    await asyncio.sleep(0.01)
    task.cancel()
    assert await finishes(task)
    assert seen == [cause]


# --- the relay, with a Redis client that misbehaves ----------------------------------------------


class FakePubSub:
    """Stands in for redis-py's `PubSub` with the two misbehaviours seen on Python 3.11."""

    def __init__(self, *, eat_cancel_in_subscribe: bool, error_on_exit: bool) -> None:
        self._eat = eat_cancel_in_subscribe
        self._error_on_exit = error_on_exit

    async def __aenter__(self) -> FakePubSub:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._error_on_exit:
            raise RedisConnectionError("Connection closed by server.")

    async def subscribe(self, channel: str) -> None:
        if self._eat:
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                return  # swallowed: returns normally with the cancel still pending
        else:
            await asyncio.sleep(0)

    async def get_message(self, **_kw: Any) -> None:
        await asyncio.sleep(0.05)
        return None


class FakeRedis:
    def __init__(self, **misbehaviour: bool) -> None:
        self._misbehaviour = misbehaviour

    def pubsub(self) -> FakePubSub:
        return FakePubSub(
            eat_cancel_in_subscribe=self._misbehaviour.get("eat_cancel_in_subscribe", False),
            error_on_exit=self._misbehaviour.get("error_on_exit", False),
        )


@pytest.mark.parametrize(
    "misbehaviour",
    [
        {},
        {"eat_cancel_in_subscribe": True},
        {"error_on_exit": True},
        {"eat_cancel_in_subscribe": True, "error_on_exit": True},
    ],
    ids=["well-behaved", "cancel-swallowed", "error-on-exit", "both"],
)
async def test_the_relay_stops_when_cancelled_however_redis_reacts(
    misbehaviour, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A long reconnect delay: a relay that took the error for a lost connection would sit in it.
    monkeypatch.setattr("api.realtime.relay.RECONNECT_BACKOFF_S", (30.0,))
    relay = RedisRelay(FakeRedis(**misbehaviour), ConnectionHub())  # type: ignore[arg-type]
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.05)  # inside subscribe() for the swallowing client
    task.cancel()
    assert await finishes(task, 1.5), "the relay is still running after cancel()"
    assert task.cancelled()


async def test_the_relay_still_reconnects_after_an_error_when_nobody_cancelled() -> None:
    attempts = 0

    class Flaky(FakeRedis):
        def pubsub(self) -> FakePubSub:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RedisConnectionError("refused")
            return super().pubsub()

    import api.realtime.relay as relay_module

    original = relay_module.RECONNECT_BACKOFF_S
    relay_module.RECONNECT_BACKOFF_S = (0.01,)
    try:
        task = asyncio.create_task(RedisRelay(Flaky(), ConnectionHub()).run())  # type: ignore[arg-type]
        await asyncio.sleep(0.3)
        assert attempts >= 2 and not task.done()
        task.cancel()
        assert await finishes(task)
    finally:
        relay_module.RECONNECT_BACKOFF_S = original
