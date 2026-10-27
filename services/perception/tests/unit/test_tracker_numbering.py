"""Track numbers must not repeat across perception runs (found 2026-10-27).

Tracks are stored under `{camera}-t{n}` with idempotent writes. A run that restarted its counter at
0 after the Redis checkpoint had expired reused the numbers of tracks stored by an earlier run of
the same camera: its new tracks were dropped and the old ones' vectors overwritten."""

from __future__ import annotations

import json
import time

import numpy as np
import pytest
from fakeredis import FakeAsyncRedis
from perception.adapters.tracker import REDIS_KEY_PREFIX, PersistentTracker

NOW_MS = 1_793_026_492_123


@pytest.fixture
def redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=True)


def person(x: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.array([[x, 100.0, x + 60.0, 220.0]]),
        np.array([0.9]),
        np.array([0]),
    )


def numbers_of(tracker: PersistentTracker, frames: int = 4) -> set[int]:
    seen: set[int] = set()
    for i in range(frames):
        for obj in tracker.assign(*person(100.0 + 3 * i)):
            seen.add(obj.track_num)
    return seen


async def test_a_first_run_starts_at_the_clock_not_at_zero(redis: FakeAsyncRedis) -> None:
    tracker = PersistentTracker("cam01", redis_client=redis, clock_ms=lambda: NOW_MS)
    await tracker.restore()

    seen = numbers_of(tracker)

    assert seen and min(seen) >= NOW_MS
    assert tracker.track_id_for(min(seen)) == f"cam01-t{min(seen)}"


async def test_a_run_after_the_checkpoint_expired_cannot_reuse_the_numbers_of_the_one_before(
    redis: FakeAsyncRedis,
) -> None:
    first = PersistentTracker("cam01", redis_client=redis, clock_ms=lambda: NOW_MS)
    await first.restore()
    used = numbers_of(first)
    await first.checkpoint()
    await redis.delete(f"{REDIS_KEY_PREFIX}cam01")  # the 7-day TTL, or a flush

    later = PersistentTracker("cam01", redis_client=redis, clock_ms=lambda: NOW_MS + 60_000)
    await later.restore()
    fresh = numbers_of(later)

    assert used and fresh and not (used & fresh)


async def test_a_restart_with_a_checkpoint_carries_on_from_where_it_was(
    redis: FakeAsyncRedis,
) -> None:
    first = PersistentTracker("cam01", redis_client=redis, clock_ms=lambda: NOW_MS)
    await first.restore()
    used = numbers_of(first)
    await first.checkpoint()

    # the clock has moved a lot, but the checkpoint decides
    later = PersistentTracker("cam01", redis_client=redis, clock_ms=lambda: NOW_MS + 10**9)
    await later.restore()
    state = json.loads(await redis.get(f"{REDIS_KEY_PREFIX}cam01"))

    assert state["next_track_num"] == max(used) + 1
    assert later._next_track_num == max(used) + 1


async def test_cameras_are_numbered_separately_but_each_from_the_clock(
    redis: FakeAsyncRedis,
) -> None:
    a = PersistentTracker("cam01", redis_client=redis, clock_ms=lambda: NOW_MS)
    b = PersistentTracker("cam02", redis_client=redis, clock_ms=lambda: NOW_MS)
    await a.restore()
    await b.restore()
    assert min(numbers_of(a)) >= NOW_MS and min(numbers_of(b)) >= NOW_MS
    assert a.track_id_for(NOW_MS).startswith("cam01-") and b.track_id_for(NOW_MS).startswith(
        "cam02-"
    )


def test_without_a_restore_a_tracker_counts_from_zero_as_the_smoke_checks_expect() -> None:
    tracker = PersistentTracker("cam01", redis_client=FakeAsyncRedis(), clock_ms=lambda: NOW_MS)
    assert min(numbers_of(tracker)) == 0


async def test_the_real_clock_is_in_milliseconds(redis: FakeAsyncRedis) -> None:
    before = int(time.time() * 1000)
    tracker = PersistentTracker("cam01", redis_client=redis)
    await tracker.restore()
    assert before <= tracker._next_track_num <= int(time.time() * 1000)
