import asyncio

import pytest
from ingestion.adapters.segmenter import StreamStalledError, watch_for_stall


async def test_a_segmenter_with_no_progress_is_declared_stalled():
    now = {"t": 100.0}
    progress = {"at": 100.0}

    async def fake_sleep(_):
        now["t"] += 5  # five seconds pass per poll

    with pytest.raises(StreamStalledError, match="no segment completed"):
        await watch_for_stall(progress, 30, poll_s=5, clock=lambda: now["t"], sleep=fake_sleep)
    assert now["t"] - progress["at"] > 30  # it fired only after the bound, not before


async def test_progress_keeps_it_quiet_and_cancelling_it_is_clean():
    now = {"t": 0.0}
    progress = {"at": 0.0}
    polls = {"n": 0}

    async def fake_sleep(_):
        polls["n"] += 1
        now["t"] += 5
        progress["at"] = now["t"]  # a segment completes every poll
        await asyncio.sleep(0)

    task = asyncio.create_task(
        watch_for_stall(progress, 30, poll_s=5, clock=lambda: now["t"], sleep=fake_sleep)
    )
    await asyncio.sleep(0.05)
    assert not task.done() and polls["n"] > 3
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
