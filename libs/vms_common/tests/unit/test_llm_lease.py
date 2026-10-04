"""GPU lease: one model family on the GPU at a time (design_architecture.md §11.3)."""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest
import redis.exceptions
from fakeredis import FakeAsyncRedis
from prometheus_client import REGISTRY
from vms_common.llm.errors import GPULeaseTimeoutError, LLMUnavailableError
from vms_common.llm.lease import GPULease

VL = "ollama:qwen2.5vl:3b"
TXT = "ollama:qwen2.5:3b"
HF = "hf_local:Qwen/Qwen2.5-VL-3B-Instruct"


def lease_for(client: FakeAsyncRedis, **kw) -> GPULease:
    return GPULease(client, **{"node": "t", "ttl_s": 5.0, "poll_s": 0.02, **kw})


async def test_a_free_gpu_is_granted_immediately_with_nothing_to_unload(redis_client) -> None:
    lease = lease_for(redis_client)
    async with lease.hold(VL, wait_s=1) as grant:
        assert grant.family == VL
        assert grant.previous_family is None
        assert await lease.current_family() == VL
    assert await lease.current_family() is None


async def test_calls_of_the_same_family_share_the_gpu(redis_client) -> None:
    lease = lease_for(redis_client)
    async with lease.hold(VL, wait_s=1), lease.hold(VL, wait_s=0.1) as second:
        assert second.previous_family is None  # same family: nothing to unload
        assert await lease.current_family() == VL


async def test_a_different_family_waits_until_every_holder_has_released(redis_client) -> None:
    lease = lease_for(redis_client)
    events: list[str] = []

    async def text_call() -> None:
        async with lease.hold(TXT, wait_s=2):
            events.append("txt-in")
            await asyncio.sleep(0.05)
            events.append("txt-out")

    async with lease.hold(VL, wait_s=1):
        waiter = asyncio.create_task(text_call())
        await asyncio.sleep(0.15)  # several polls
        assert events == []  # still blocked while VL holds the GPU
        events.append("vl-release")
    await waiter
    assert events == ["vl-release", "txt-in", "txt-out"]


async def test_switching_families_reports_the_previous_one_for_unloading(redis_client) -> None:
    lease = lease_for(redis_client)
    async with lease.hold(VL, wait_s=1):
        pass
    async with lease.hold(TXT, wait_s=1) as grant:
        assert grant.previous_family == VL
    async with lease.hold(TXT, wait_s=1) as grant:
        assert grant.previous_family is None  # TXT is what is loaded now
    async with lease.hold(VL, wait_s=1) as grant:
        assert grant.previous_family == TXT


async def test_waiting_too_long_raises_a_timeout_naming_the_holder(redis_client) -> None:
    lease = lease_for(redis_client)
    async with lease.hold(VL, wait_s=1):
        started = time.monotonic()
        with pytest.raises(GPULeaseTimeoutError, match=r"held by ollama:qwen2\.5vl:3b") as caught:
            async with lease.hold(TXT, wait_s=0.1):
                pytest.fail("should not have been granted")
        assert 0.09 <= time.monotonic() - started < 1.0
        assert isinstance(caught.value, LLMUnavailableError)  # so fallbacks kick in


async def test_zero_wait_fails_straight_away_when_busy(redis_client) -> None:
    lease = lease_for(redis_client)
    async with lease.hold(VL, wait_s=1):
        with pytest.raises(GPULeaseTimeoutError):
            async with lease.hold(TXT, wait_s=0):
                pytest.fail("should not have been granted")


async def test_a_waiting_family_is_not_starved_by_a_stream_of_the_current_one(redis_client) -> None:
    lease = lease_for(redis_client)
    got_gpu = asyncio.Event()

    async def text_call() -> None:
        async with lease.hold(TXT, wait_s=3):
            got_gpu.set()

    async with lease.hold(VL, wait_s=1):
        waiter = asyncio.create_task(text_call())
        await asyncio.sleep(0.1)  # TXT has queued: it is now first in line
        # A *new* VL call must not slip in ahead of the queued TXT call ...
        with pytest.raises(GPULeaseTimeoutError):
            async with lease.hold(VL, wait_s=0.1):
                pytest.fail("jumped the queue")
    # ... and once VL releases, TXT gets the GPU.
    await asyncio.wait_for(got_gpu.wait(), 2)
    await waiter


async def test_a_waiter_that_gives_up_withdraws_its_place_in_the_queue(redis_client) -> None:
    lease = lease_for(redis_client, poll_s=0.02)
    async with lease.hold(VL, wait_s=1):
        with pytest.raises(GPULeaseTimeoutError):
            async with lease.hold(TXT, wait_s=0.1):
                pytest.fail("held")
        # The TXT caller is gone, so it must not keep new VL calls waiting behind it.
        async with lease.hold(VL, wait_s=0.05):
            pass


async def test_a_waiter_that_is_cancelled_also_withdraws(redis_client) -> None:
    lease = lease_for(redis_client)
    async with lease.hold(VL, wait_s=1):
        waiter = await _queue_waiter(lease, TXT)
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter
        async with lease.hold(VL, wait_s=0.05):
            pass


async def test_withdrawing_never_removes_another_familys_place(redis_client) -> None:
    lease = lease_for(redis_client)
    async with lease.hold(HF, wait_s=1):
        queued = await _queue_waiter(lease, TXT)  # TXT is first in line
        with pytest.raises(GPULeaseTimeoutError):
            async with lease.hold(VL, wait_s=0.05):  # VL is behind TXT, gives up, withdraws
                pytest.fail("held")
        assert await redis_client.get("gpu:lease:t:pending") == TXT  # TXT's place survived
        queued.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await queued


async def test_a_crashed_holder_stops_blocking_once_its_ttl_lapses(redis_client) -> None:
    crashed = lease_for(redis_client, ttl_s=0.3)
    survivor = lease_for(redis_client, ttl_s=0.3)
    # Simulate a process that took the lease and died: acquire without ever heartbeating/releasing.
    granted, _ = await crashed._acquire_script(
        keys=[crashed._holders_key, crashed._pending_key, crashed._loaded_key],
        args=[VL, "dead-process", 300, 2000],
    )
    assert granted == 1
    started = time.monotonic()
    async with survivor.hold(TXT, wait_s=3) as grant:
        assert 0.25 <= time.monotonic() - started < 2.5  # waited for the TTL, not forever
        assert grant.previous_family == VL  # and knows what to unload


async def test_a_dead_holder_beside_a_live_one_is_purged_when_the_gpu_is_next_wanted(
    redis_client,
) -> None:
    gpu = lease_for(redis_client, ttl_s=0.3)
    # A process that took the lease and died, while a live holder of the same family keeps the
    # holder set (and its key TTL) refreshed — only the purge can remove the dead entry.
    granted, _ = await gpu._acquire_script(
        keys=[gpu._holders_key, gpu._pending_key, gpu._loaded_key],
        args=[VL, "dead-process", 200, 2000],
    )
    assert granted == 1
    async with gpu.hold(VL, wait_s=1):
        await asyncio.sleep(0.5)  # the dead entry has expired; the live holder beats on
    # Nothing is live any more, so another family must get in at once, not after the key lapses.
    async with gpu.hold(TXT, wait_s=0.1) as grant:
        assert grant.previous_family == VL


async def test_the_heartbeat_keeps_a_long_call_from_expiring(redis_client) -> None:
    lease = lease_for(redis_client, ttl_s=0.3)
    other = lease_for(redis_client, ttl_s=0.3)
    async with lease.hold(VL, wait_s=1):
        await asyncio.sleep(0.9)  # three TTLs
        assert await lease.current_family() == VL
        with pytest.raises(GPULeaseTimeoutError):
            async with other.hold(TXT, wait_s=0.05):
                pytest.fail("the live holder must still own the GPU")


async def test_a_released_lease_cannot_be_renewed_back_to_life(redis_client) -> None:
    lease = lease_for(redis_client, ttl_s=0.3)
    async with lease.hold(VL, wait_s=1):
        pass
    renewed = await lease._heartbeat_script(
        keys=[lease._holders_key], args=[f"{VL}|{'0' * 32}", 300]
    )
    assert renewed == 0
    assert await lease.current_family() is None


async def test_release_happens_even_when_the_call_body_raises(redis_client) -> None:
    lease = lease_for(redis_client)
    with pytest.raises(RuntimeError, match="boom"):
        async with lease.hold(VL, wait_s=1):
            raise RuntimeError("boom")
    assert await lease.current_family() is None
    async with lease.hold(TXT, wait_s=0.1):
        pass


async def test_release_happens_when_the_holding_task_is_cancelled(redis_client) -> None:
    lease = lease_for(redis_client)
    inside = asyncio.Event()

    async def hold_forever() -> None:
        async with lease.hold(VL, wait_s=1):
            inside.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(hold_forever())
    await inside.wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert await lease.current_family() is None


async def test_cancelling_a_queued_waiter_leaves_the_gpu_with_its_owner(redis_client) -> None:
    lease = lease_for(redis_client)
    async with lease.hold(VL, wait_s=1):
        waiter = await _queue_waiter(lease, TXT)
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter
        assert await lease.current_family() == VL


async def _hold(lease: GPULease, family: str, *, wait_s: float) -> None:
    async with lease.hold(family, wait_s=wait_s):
        await asyncio.sleep(0)


async def _queue_waiter(lease: GPULease, family: str, *, wait_s: float = 5) -> asyncio.Task[None]:
    """Start a waiter and return once it has polled the lease and gone back to sleep.

    Cancelling a waiter *during* a Redis command is not something fakeredis handles faithfully
    (it can swallow the cancellation; real Redis does not — see the integration test), so tests
    that cancel a waiter do it only at this known-safe moment instead of after a fixed sleep.
    """
    polled = asyncio.Event()
    real = lease._acquire_script

    async def spy(*args, **kwargs):
        result = await real(*args, **kwargs)
        polled.set()
        return result

    lease._acquire_script = spy  # type: ignore[assignment]
    task = asyncio.create_task(_hold(lease, family, wait_s=wait_s))
    await polled.wait()  # the waiter runs on, synchronously, into its sleep before we resume
    return task


async def test_nodes_have_independent_leases(redis_client) -> None:
    a = lease_for(redis_client, node="laptop-a")
    b = lease_for(redis_client, node="laptop-b")
    async with a.hold(VL, wait_s=1), b.hold(TXT, wait_s=0.1):
        assert await a.current_family() == VL
        assert await b.current_family() == TXT


async def test_two_processes_share_one_lease_through_redis(redis_client) -> None:
    first, second = lease_for(redis_client), lease_for(redis_client)
    async with first.hold(HF, wait_s=1):
        with pytest.raises(GPULeaseTimeoutError):
            async with second.hold(VL, wait_s=0.05):
                pytest.fail("held")
        async with second.hold(HF, wait_s=0.1):  # same family from another process is fine
            pass


async def test_many_concurrent_calls_of_two_families_never_overlap(redis_client) -> None:
    lease = lease_for(redis_client, poll_s=0.01)
    active: dict[str, int] = {VL: 0, TXT: 0}
    overlaps: list[str] = []
    done = 0

    async def call(family: str) -> None:
        nonlocal done
        async with lease.hold(family, wait_s=20):
            active[family] += 1
            if any(n for fam, n in active.items() if fam != family):
                overlaps.append(family)
            await asyncio.sleep(0.01)
            active[family] -= 1
        done += 1

    await asyncio.gather(*(call(VL if i % 2 else TXT) for i in range(24)))
    assert done == 24
    assert overlaps == []


async def test_redis_being_down_is_an_unavailable_error_not_an_unleased_run() -> None:
    client = FakeAsyncRedis(decode_responses=True)
    lease = lease_for(client)

    async def boom(*_a, **_k):
        raise redis.exceptions.ConnectionError("redis is down")

    lease._acquire_script = boom  # type: ignore[assignment]
    with pytest.raises(LLMUnavailableError, match="GPU lease unavailable"):
        async with lease.hold(VL, wait_s=1):
            pytest.fail("must not run a heavy model without the lease")
    await client.aclose()


async def test_family_names_cannot_smuggle_the_member_separator(redis_client) -> None:
    lease = lease_for(redis_client)
    with pytest.raises(ValueError, match=r"'\|'"):
        async with lease.hold("a|b", wait_s=1):
            pass


def test_nonsense_timings_are_rejected(redis_client) -> None:
    with pytest.raises(ValueError):
        GPULease(redis_client, ttl_s=0)
    with pytest.raises(ValueError):
        GPULease(redis_client, poll_s=-1)


async def test_wait_outcomes_are_recorded_as_metrics(redis_client) -> None:
    lease = lease_for(redis_client)

    def observations(outcome: str) -> float:
        return (
            REGISTRY.get_sample_value("vms_llm_lease_wait_seconds_count", {"outcome": outcome}) or 0
        )

    granted_before, timeout_before = observations("granted"), observations("timeout")
    async with lease.hold(VL, wait_s=1):
        with pytest.raises(GPULeaseTimeoutError):
            async with lease.hold(TXT, wait_s=0.05):
                pass
    assert observations("granted") == granted_before + 1
    assert observations("timeout") == timeout_before + 1
