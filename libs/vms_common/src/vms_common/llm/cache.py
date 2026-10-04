"""Redis response cache. Free-tier quotas are small (context.md: "cache aggressively"), and
re-running a search or re-verifying an identical event sends the identical request.

Key = hash(task, model, messages, response schema, sampling params) — images are part of the
messages (as data URLs), so a different frame is a different key — so switching
profile or editing a prompt can never serve an answer produced for a different request. Only
validated results are stored. A Redis outage is a cache miss, never a failed LLM call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from vms_common.llm.registry import ModelRef
from vms_common.logging import get_logger

log = get_logger(__name__)

KEY_PREFIX = "vms:llm:cache:"
KEY_VERSION = 1  # bump when the stored shape changes so old entries are ignored
_REDIS_TIMEOUT_S = 2.0


def cache_key(
    *,
    task: str,
    ref: ModelRef,
    messages: list[dict[str, Any]],
    response_schema: dict[str, Any] | None,
    temperature: float,
    max_tokens: int | None,
) -> str:
    payload = {
        "v": KEY_VERSION,
        "task": task,
        "provider": ref.provider,
        "model": ref.model,
        "adapter": ref.adapter,
        "messages": messages,
        "schema": response_schema,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return KEY_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            async with asyncio.timeout(_REDIS_TIMEOUT_S):
                raw = await self._client.get(key)
        except (RedisError, OSError, TimeoutError) as exc:
            log.warning("llm_cache_unavailable", op="get", error=type(exc).__name__)
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            log.warning("llm_cache_entry_corrupt", key=key)
            return None
        return value if isinstance(value, dict) else None

    async def set(self, key: str, value: dict[str, Any], *, ttl_s: int) -> None:
        try:
            async with asyncio.timeout(_REDIS_TIMEOUT_S):
                await self._client.set(key, json.dumps(value, separators=(",", ":")), ex=ttl_s)
        except (RedisError, OSError, TimeoutError) as exc:
            log.warning("llm_cache_unavailable", op="set", error=type(exc).__name__)
