"""`_stop_tasks`: shutdown waits for background tasks, but not for ever (P3-J3)."""

from __future__ import annotations

import asyncio

import api.main as main_module
import pytest
from api.main import _stop_tasks


class RecordingLog:
    """Stands in for `api.main.log`. structlog caches a logger on first use
    (`cache_logger_on_first_use`), so once any earlier test has logged from `api.main`,
    `structlog.testing.capture_logs` no longer sees it: replace the logger itself."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def error(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))

    info = warning = error


async def test_cooperative_tasks_are_cancelled_and_awaited() -> None:
    tasks = [asyncio.create_task(asyncio.sleep(3600)) for _ in range(3)]
    await asyncio.sleep(0)
    await _stop_tasks(tasks, grace_s=2.0)
    assert all(t.cancelled() for t in tasks)


async def test_a_task_that_ignores_cancellation_is_abandoned_after_the_grace_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RecordingLog()
    monkeypatch.setattr(main_module, "log", recorder)
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

        await _stop_tasks([task], grace_s=0.2)

        assert asyncio.get_running_loop().time() - began < 1.0  # bounded, not stuck
        assert not task.done()
        stuck = [
            fields for event, fields in recorder.events if event == "background_task_did_not_stop"
        ]
        assert [f["task"] for f in stuck] == ["stubborn"]
    finally:
        release.set()  # whatever happened above, never leave an uncancellable task behind
        await task


async def test_no_tasks_is_fine() -> None:
    await _stop_tasks([], grace_s=0.1)
