"""`_stop_tasks`: shutdown waits for background tasks, but not for ever (P3-J3)."""

from __future__ import annotations

import asyncio

from api.main import _stop_tasks
from structlog.testing import capture_logs


async def test_cooperative_tasks_are_cancelled_and_awaited() -> None:
    tasks = [asyncio.create_task(asyncio.sleep(3600)) for _ in range(3)]
    await asyncio.sleep(0)
    await _stop_tasks(tasks, grace_s=2.0)
    assert all(t.cancelled() for t in tasks)


async def test_a_task_that_ignores_cancellation_is_abandoned_after_the_grace_period() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def ignores_cancel() -> None:
        started.set()
        while not release.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                continue  # a library eating the cancellation

    task = asyncio.create_task(ignores_cancel(), name="stubborn")
    try:
        await started.wait()
        began = asyncio.get_running_loop().time()

        with capture_logs() as logs:
            await _stop_tasks([task], grace_s=0.2)

        assert asyncio.get_running_loop().time() - began < 1.0  # bounded, not stuck
        assert not task.done()
        stuck = [e for e in logs if e["event"] == "background_task_did_not_stop"]
        assert [e["task"] for e in stuck] == ["stubborn"]
    finally:
        release.set()  # whatever happened above, never leave an uncancellable task behind
        await task


async def test_no_tasks_is_fine() -> None:
    await _stop_tasks([], grace_s=0.1)
