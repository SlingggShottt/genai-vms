"""`supervise` keeps a consumer alive and still stops when told to (P3-J3)."""

from __future__ import annotations

import asyncio
import types
from collections.abc import Awaitable, Callable

import pytest
from api.consumers import supervisor
from api.consumers.supervisor import supervise


class FakeConsumer:
    def __init__(
        self,
        run: Callable[[FakeConsumer], Awaitable[None]],
        *,
        start_error: Exception | None = None,
    ) -> None:
        self._run, self._start_error = run, start_error
        self.started = self.stopped = 0

    async def start(self) -> None:
        self.started += 1
        if self._start_error:
            raise self._start_error

    async def run(self) -> None:
        await self._run(self)

    async def stop(self) -> None:
        self.stopped += 1


async def block_forever(_c: FakeConsumer) -> None:
    await asyncio.Event().wait()


async def fail(_c: FakeConsumer) -> None:
    raise RuntimeError("broker went away")


async def finishes(task: asyncio.Task, within_s: float = 3.0) -> bool:
    done, _pending = await asyncio.wait({task}, timeout=within_s)
    return bool(done)


def factory(*consumers: FakeConsumer) -> tuple[Callable[[], FakeConsumer], list[FakeConsumer]]:
    made: list[FakeConsumer] = []
    queue = list(consumers)

    def make() -> FakeConsumer:
        consumer = queue.pop(0) if len(queue) > 1 else queue[0]  # the last one is reused
        made.append(consumer)
        return consumer

    return make, made


async def test_a_healthy_consumer_runs_until_cancelled_then_is_stopped() -> None:
    make, made = factory(FakeConsumer(block_forever))
    task = asyncio.create_task(supervise("t", make, backoff=(0.01,)))
    await asyncio.sleep(0.05)
    task.cancel()
    assert await finishes(task) and task.cancelled()
    assert made[0].started == 1 and made[0].stopped == 1


async def test_a_crashed_consumer_is_replaced() -> None:
    second_running = asyncio.Event()

    async def second(c: FakeConsumer) -> None:
        second_running.set()
        await block_forever(c)

    crashing, healthy = FakeConsumer(fail), FakeConsumer(second)
    make, made = factory(crashing, healthy)
    task = asyncio.create_task(supervise("t", make, backoff=(0.01,)))
    await asyncio.wait_for(second_running.wait(), 3)
    task.cancel()
    await finishes(task)
    assert crashing.stopped == 1  # the dead one was cleaned up before the replacement started
    assert made == [crashing, healthy]


async def test_a_consumer_that_cannot_start_is_retried() -> None:
    unreachable = FakeConsumer(block_forever, start_error=ConnectionError("no broker"))
    ok_running = asyncio.Event()

    async def ok(c: FakeConsumer) -> None:
        ok_running.set()
        await block_forever(c)

    make, made = factory(unreachable, FakeConsumer(ok))
    task = asyncio.create_task(supervise("t", make, backoff=(0.01,)))
    await asyncio.wait_for(ok_running.wait(), 3)
    task.cancel()
    await finishes(task)
    assert unreachable.started == 1 and unreachable.stopped == 1  # stop() after a failed start


async def test_a_consumer_whose_run_returns_is_restarted_not_dropped() -> None:
    async def returns(_c: FakeConsumer) -> None:
        return None

    again = asyncio.Event()

    async def second(c: FakeConsumer) -> None:
        again.set()
        await block_forever(c)

    make, made = factory(FakeConsumer(returns), FakeConsumer(second))
    task = asyncio.create_task(supervise("t", make, backoff=(0.01,)))
    await asyncio.wait_for(again.wait(), 3)
    task.cancel()
    await finishes(task)
    assert len(made) == 2


async def test_a_failing_stop_does_not_end_the_supervisor() -> None:
    class BadStop(FakeConsumer):
        async def stop(self) -> None:
            await super().stop()
            raise RuntimeError("stop blew up")

    again = asyncio.Event()

    async def second(c: FakeConsumer) -> None:
        again.set()
        await block_forever(c)

    make, _ = factory(BadStop(fail), FakeConsumer(second))
    task = asyncio.create_task(supervise("t", make, backoff=(0.01,)))
    await asyncio.wait_for(again.wait(), 3)
    task.cancel()
    await finishes(task)


@pytest.mark.parametrize("how", ["swallowed", "replaced"])
async def test_cancellation_wins_even_when_the_consumer_mangles_it(how: str) -> None:
    async def mangle(_c: FakeConsumer) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if how == "replaced":
                raise RuntimeError("kafka connection closed") from None
            # "swallowed": return normally, as if the consumer had simply stopped

    make, made = factory(FakeConsumer(mangle))
    task = asyncio.create_task(supervise("t", make, backoff=(5.0,)))  # a restart would be slow
    await asyncio.sleep(0.05)
    task.cancel()
    assert await finishes(task, 1.0), "the supervisor went on to restart a cancelled consumer"
    assert task.cancelled() and len(made) == 1


async def test_the_delay_grows_to_the_last_step_then_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    async def record(seconds: float) -> None:
        delays.append(seconds)
        if len(delays) >= 6:
            raise asyncio.CancelledError
        await asyncio.sleep(0)

    monkeypatch.setattr(
        supervisor,
        "asyncio",
        types.SimpleNamespace(
            sleep=record,
            CancelledError=asyncio.CancelledError,
            current_task=asyncio.current_task,
        ),
    )
    make, _ = factory(FakeConsumer(fail))
    with pytest.raises(asyncio.CancelledError):
        await supervise("t", make, backoff=(1.0, 2.0, 5.0))
    assert delays == [1.0, 2.0, 5.0, 5.0, 5.0, 5.0]


async def test_a_consumer_that_ran_long_enough_restarts_from_the_first_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    async def record(seconds: float) -> None:
        delays.append(seconds)
        if len(delays) >= 4:
            raise asyncio.CancelledError
        await asyncio.sleep(0)

    monkeypatch.setattr(supervisor, "HEALTHY_AFTER_S", 0.0)  # every run counts as long enough
    monkeypatch.setattr(
        supervisor,
        "asyncio",
        types.SimpleNamespace(
            sleep=record,
            CancelledError=asyncio.CancelledError,
            current_task=asyncio.current_task,
        ),
    )
    make, _ = factory(FakeConsumer(fail))
    with pytest.raises(asyncio.CancelledError):
        await supervise("t", make, backoff=(1.0, 2.0, 5.0))
    assert delays == [1.0, 1.0, 1.0, 1.0]
