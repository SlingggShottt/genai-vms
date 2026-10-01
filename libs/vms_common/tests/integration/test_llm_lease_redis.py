"""Integration test: the GPU lease's Lua scripts and the response cache on a real Redis.

Run via `make test-int` (needs Docker). The unit tests run the same logic on fakeredis; this
is the check that real Redis agrees (TIME, sorted-set scores, PX markers, PEXPIRE, EVALSHA).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Iterator

import pytest
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer
from vms_common.llm.cache import ResponseCache
from vms_common.llm.errors import GPULeaseTimeoutError
from vms_common.llm.lease import GPULease

pytestmark = pytest.mark.integration

VL = "ollama:qwen2.5vl:3b"
TXT = "ollama:qwen2.5:3b"


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture
async def client(redis_url: str) -> AsyncIterator[Redis]:
    redis = Redis.from_url(redis_url, decode_responses=True)
    await redis.flushdb()
    yield redis
    await redis.aclose()


def lease(client: Redis, **kw) -> GPULease:
    return GPULease(client, **{"node": "it", "ttl_s": 5.0, "poll_s": 0.02, **kw})


async def test_same_family_shares_and_a_different_family_waits(client: Redis) -> None:
    gpu = lease(client)
    async with gpu.hold(VL, wait_s=1), gpu.hold(VL, wait_s=0.1):
        assert await gpu.current_family() == VL
        with pytest.raises(GPULeaseTimeoutError, match="held by"):
            async with gpu.hold(TXT, wait_s=0.1):
                pytest.fail("granted while another family held the GPU")
    assert await gpu.current_family() is None


async def test_switching_families_reports_the_previous_one(client: Redis) -> None:
    gpu = lease(client)
    async with gpu.hold(VL, wait_s=1) as first:
        assert first.previous_family is None
    async with gpu.hold(TXT, wait_s=1) as second:
        assert second.previous_family == VL
    assert await client.get("gpu:loaded:it") == TXT


async def test_two_connections_behave_as_two_processes(redis_url: str, client: Redis) -> None:
    other_client = Redis.from_url(redis_url, decode_responses=True)
    first, second = lease(client), lease(other_client)
    order: list[str] = []

    async def text_call() -> None:
        async with second.hold(TXT, wait_s=3):
            order.append("txt")

    async with first.hold(VL, wait_s=1):
        task = asyncio.create_task(text_call())
        await asyncio.sleep(0.15)
        assert order == []
        order.append("vl-done")
    await task
    assert order == ["vl-done", "txt"]
    await other_client.aclose()


async def test_a_dead_holder_frees_the_gpu_after_its_ttl_on_the_real_clock(client: Redis) -> None:
    gpu = lease(client, ttl_s=0.4)
    granted, _ = await gpu._acquire_script(
        keys=[gpu._holders_key, gpu._pending_key, gpu._loaded_key],
        args=[VL, "dead", 400, 2000],
    )
    assert granted == 1
    started = time.monotonic()
    async with gpu.hold(TXT, wait_s=3) as grant:
        assert 0.3 <= time.monotonic() - started < 2.5
        assert grant.previous_family == VL


async def test_the_heartbeat_outlives_several_ttls(client: Redis) -> None:
    gpu, rival = lease(client, ttl_s=0.4), lease(client, ttl_s=0.4)
    async with gpu.hold(VL, wait_s=1):
        await asyncio.sleep(1.3)  # > 3 TTLs
        assert await gpu.current_family() == VL
        with pytest.raises(GPULeaseTimeoutError):
            async with rival.hold(TXT, wait_s=0.05):
                pytest.fail("the live holder lost the GPU")


async def test_a_waiter_that_gives_up_withdraws_and_the_queue_marker_has_a_ttl(
    client: Redis,
) -> None:
    gpu = lease(client)
    async with gpu.hold(VL, wait_s=1):
        waiter = asyncio.create_task(_try(gpu, TXT, 5))
        await asyncio.sleep(0.1)
        assert await client.get("gpu:lease:it:pending") == TXT
        assert 0 < await client.pttl("gpu:lease:it:pending") <= 2000  # lapses by itself
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter
        assert await client.get("gpu:lease:it:pending") is None  # withdrawn on cancel
        async with gpu.hold(VL, wait_s=0.05):  # and nobody is held up behind a ghost
            pass


async def _try(gpu: GPULease, family: str, wait_s: float) -> None:
    async with gpu.hold(family, wait_s=wait_s):
        await asyncio.sleep(0)


async def test_the_holder_set_carries_a_ttl_so_a_dead_fleet_leaves_no_litter(client: Redis) -> None:
    gpu = lease(client, ttl_s=0.5)
    async with gpu.hold(VL, wait_s=1):
        assert 0 < await client.pttl("gpu:lease:it") <= 1000


async def test_the_scripts_reload_after_redis_forgets_them(client: Redis) -> None:
    gpu = lease(client)
    async with gpu.hold(VL, wait_s=1):
        pass
    await client.script_flush()  # what a Redis restart does to cached scripts
    async with gpu.hold(TXT, wait_s=1) as grant:  # EVALSHA misses, redis-py reloads and retries
        assert grant.previous_family == VL


async def test_many_calls_of_two_families_never_overlap_across_connections(
    redis_url: str, client: Redis
) -> None:
    other_client = Redis.from_url(redis_url, decode_responses=True)
    leases = [lease(client, poll_s=0.01), lease(other_client, poll_s=0.01)]
    active = {VL: 0, TXT: 0}
    overlaps: list[str] = []

    async def call(i: int) -> None:
        family = VL if i % 3 else TXT
        async with leases[i % 2].hold(family, wait_s=30):
            active[family] += 1
            if any(n for f, n in active.items() if f != family):
                overlaps.append(family)
            await asyncio.sleep(0.01)
            active[family] -= 1

    await asyncio.gather(*(call(i) for i in range(30)))
    assert overlaps == []
    await other_client.aclose()


async def test_cache_round_trip_with_a_real_ttl(client: Redis) -> None:
    cache = ResponseCache(client)
    await cache.set("vms:llm:cache:k", {"text": "hello", "usage": {"prompt_tokens": 3}}, ttl_s=60)
    assert await cache.get("vms:llm:cache:k") == {"text": "hello", "usage": {"prompt_tokens": 3}}
    assert 0 < await client.ttl("vms:llm:cache:k") <= 60
    await cache.set("vms:llm:cache:short", {"text": "x"}, ttl_s=1)
    await asyncio.sleep(1.2)
    assert await cache.get("vms:llm:cache:short") is None
