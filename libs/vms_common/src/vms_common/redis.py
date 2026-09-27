"""Redis client factory. GPU lease (P3-D3), LLM response cache, WS pub/sub
fan-out, tracker checkpoints (P2-D2) and camera status heartbeats (P1-D5)
all share one client shape — this avoids duplicating connection setup.
"""

from __future__ import annotations

from redis.asyncio import Redis

from vms_common.config import RedisSettings


def get_redis_client(settings: RedisSettings | None = None) -> Redis:
    """Build an async Redis client from `settings` (or its defaults)."""
    settings = settings or RedisSettings()
    return Redis.from_url(settings.url, decode_responses=True)
