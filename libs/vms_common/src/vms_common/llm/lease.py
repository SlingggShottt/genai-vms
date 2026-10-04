"""Redis GPU lease (design_architecture.md §11.3, ADR 007).

A 4 GB GPU holds one GenAI model family at a time. The lease arbitrates between families:

- Calls of the *same* family share the lease (two event verifications may run together —
  Ollama queues them anyway); a call of a *different* family waits until every current
  holder has released.
- A waiting family goes first in line: while one is queued, the current family admits no
  new holders, so a steady stream of cheap calls cannot starve an expensive one.
- Each holder carries a TTL that a heartbeat renews. A crashed process stops renewing, so
  the GPU is never wedged for longer than `ttl_s`.
- The lease remembers which family was last *loaded*. When a different family is granted
  the lease, the gateway uses that to unload the previous one (Ollama `keep_alive: 0`).

Everything is decided inside Lua scripts so two processes cannot interleave a check and an
update, and time comes from Redis (`TIME`) rather than the callers' clocks.

Keys (all per node, so a second GPU laptop gets its own lease):
    gpu:lease:{node}          sorted set — member "<family>|<holder>", score = expiry (ms)
    gpu:lease:{node}:pending  the family first in line (short TTL, renewed by its waiters)
    gpu:loaded:{node}         the family last granted the GPU (no TTL)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from vms_common.ids import uuid7
from vms_common.llm import metrics
from vms_common.llm.errors import GPULeaseTimeoutError, LLMUnavailableError
from vms_common.logging import get_logger

log = get_logger(__name__)

# KEYS: holders, pending, loaded   ARGV: family, holder, ttl_ms, pending_ttl_ms
# Returns {1, previously_loaded_family_or_''} when granted, {0, current_family_or_''} when not.
_ACQUIRE = """
local holders, pending_key, loaded_key = KEYS[1], KEYS[2], KEYS[3]
local family, holder = ARGV[1], ARGV[2]
local ttl_ms, pending_ttl_ms = tonumber(ARGV[3]), tonumber(ARGV[4])
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)

redis.call('ZREMRANGEBYSCORE', holders, '-inf', now)
local first = redis.call('ZRANGE', holders, 0, 0)[1]
local current = false
if first then current = string.match(first, '^(.*)|[^|]*$') end
local pending = redis.call('GET', pending_key)

if pending and pending ~= family then
  return {0, current or ''}
end
if current and current ~= family then
  redis.call('SET', pending_key, family, 'PX', pending_ttl_ms)
  return {0, current}
end

redis.call('ZADD', holders, now + ttl_ms, family .. '|' .. holder)
redis.call('PEXPIRE', holders, ttl_ms * 2)
if pending == family then redis.call('DEL', pending_key) end
local previous = redis.call('GET', loaded_key)
redis.call('SET', loaded_key, family)
return {1, previous or ''}
"""

# KEYS: holders   ARGV: member, ttl_ms      → 1 renewed, 0 the holder is gone (it expired)
_HEARTBEAT = """
if not redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 0 end
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local ttl_ms = tonumber(ARGV[2])
redis.call('ZADD', KEYS[1], now + ttl_ms, ARGV[1])
redis.call('PEXPIRE', KEYS[1], ttl_ms * 2)
return 1
"""

_RELEASE = "return redis.call('ZREM', KEYS[1], ARGV[1])"

# KEYS: pending   ARGV: family   — a waiter that gives up takes its own queue marker with it
# (never another family's), so the GPU is not left refusing new calls for a waiter that is gone.
_WITHDRAW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


@dataclass(frozen=True)
class LeaseGrant:
    family: str
    # The family that was on the GPU before this grant, when it differs from `family`.
    # The caller should unload it. None = nothing to unload.
    previous_family: str | None


class GPULease:
    def __init__(
        self,
        client: Redis,
        *,
        node: str = "local",
        ttl_s: float = 30.0,
        poll_s: float = 0.25,
    ) -> None:
        if ttl_s <= 0 or poll_s <= 0:
            raise ValueError("ttl_s and poll_s must be positive")
        self._client = client
        self._node = node
        self._ttl_ms = int(ttl_s * 1000)
        self._poll_s = poll_s
        # A queued family keeps its place by renewing this marker on every poll. A waiter that
        # gives up withdraws it; if the waiter vanished outright (crash) it lapses by itself.
        self._pending_ttl_ms = max(int(poll_s * 3000), 2000)
        self._holders_key = f"gpu:lease:{node}"
        self._pending_key = f"gpu:lease:{node}:pending"
        self._loaded_key = f"gpu:loaded:{node}"
        self._acquire_script = client.register_script(_ACQUIRE)
        self._heartbeat_script = client.register_script(_HEARTBEAT)
        self._release_script = client.register_script(_RELEASE)
        self._withdraw_script = client.register_script(_WITHDRAW)

    @property
    def node(self) -> str:
        return self._node

    @asynccontextmanager
    async def hold(self, family: str, *, wait_s: float) -> AsyncIterator[LeaseGrant]:
        """Hold the GPU for `family`, queueing up to `wait_s` seconds for it.

        Raises `GPULeaseTimeoutError` if another family keeps the GPU that long, and
        `LLMUnavailableError` if Redis cannot be reached (callers must not run a heavy
        model without the lease).
        """
        if "|" in family:
            raise ValueError("family must not contain '|'")
        holder = uuid7().hex
        member = f"{family}|{holder}"
        grant = await self._acquire(family, holder, wait_s)
        beat = asyncio.create_task(self._heartbeat(member), name=f"gpu-lease-beat-{holder[:8]}")
        try:
            yield grant
        finally:
            beat.cancel()
            # gather() (not `await beat` under suppress(CancelledError)) so that a cancellation
            # aimed at *this* task during the wait is not swallowed along with the beat's own.
            await asyncio.gather(beat, return_exceptions=True)
            await self._release(member)

    async def current_family(self) -> str | None:
        """The family holding the GPU right now (for health endpoints and tests)."""
        try:
            seconds, micros = await self._client.time()  # Redis's clock, as the scripts use
            now_ms = int(seconds) * 1000 + int(micros) // 1000
            members = await self._client.zrangebyscore(self._holders_key, now_ms + 1, "+inf")
        except (RedisError, OSError) as exc:
            raise LLMUnavailableError(f"GPU lease unavailable: {exc}") from exc
        return _decode(members[0]).rsplit("|", 1)[0] if members else None

    async def _acquire(self, family: str, holder: str, wait_s: float) -> LeaseGrant:
        started = time.monotonic()
        deadline = started + wait_s
        keys = [self._holders_key, self._pending_key, self._loaded_key]
        args = [family, holder, self._ttl_ms, self._pending_ttl_ms]
        acquired = False
        try:
            while True:
                try:
                    granted, other = await self._acquire_script(keys=keys, args=args)
                except (RedisError, OSError) as exc:
                    metrics.lease_wait_seconds.labels("error").observe(time.monotonic() - started)
                    raise LLMUnavailableError(f"GPU lease unavailable: {exc}") from exc
                if granted:
                    acquired = True
                    metrics.lease_wait_seconds.labels("granted").observe(time.monotonic() - started)
                    previous = _decode(other)
                    return LeaseGrant(family, previous if previous and previous != family else None)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    metrics.lease_wait_seconds.labels("timeout").observe(time.monotonic() - started)
                    raise GPULeaseTimeoutError(
                        f"GPU {self._node!r} is held by {_decode(other) or 'another family'}; "
                        f"gave up after {wait_s:.0f}s waiting to load {family!r}"
                    )
                await asyncio.sleep(min(self._poll_s, remaining))
        finally:
            if not acquired:  # timed out, Redis failed, or the waiting task was cancelled
                await self._withdraw(family)

    async def _withdraw(self, family: str) -> None:
        try:
            await self._withdraw_script(keys=[self._pending_key], args=[family])
        except (RedisError, OSError) as exc:
            # Harmless: the marker lapses by itself within a couple of seconds.
            log.warning("gpu_lease_withdraw_failed", node=self._node, error=type(exc).__name__)

    async def _heartbeat(self, member: str) -> None:
        interval = self._ttl_ms / 3000
        while True:
            await asyncio.sleep(interval)
            try:
                alive = await self._heartbeat_script(
                    keys=[self._holders_key], args=[member, self._ttl_ms]
                )
            except (RedisError, OSError) as exc:
                # Keep trying: the TTL still has two more intervals of slack.
                log.warning("gpu_lease_heartbeat_failed", node=self._node, error=type(exc).__name__)
                continue
            if not alive:
                log.warning("gpu_lease_lost", node=self._node, member=member.rsplit("|", 1)[0])
                return  # nothing left to renew; the call in flight carries on

    async def _release(self, member: str) -> None:
        try:
            await self._release_script(keys=[self._holders_key], args=[member])
        except (RedisError, OSError) as exc:
            # The entry expires on its own within ttl_s; the call itself already finished.
            log.warning("gpu_lease_release_failed", node=self._node, error=type(exc).__name__)


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value or "")
