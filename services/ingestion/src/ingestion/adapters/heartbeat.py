"""Camera status heartbeat to Redis `camera:status:<id>` — merged by the api
service into `GET /cameras/status` (design_architecture.md §7.1, FR-CAM-02:
status updated at least every 10s; this writes every 5s).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from redis.asyncio import Redis

HEARTBEAT_INTERVAL_SECONDS = 5.0
# 3x the interval: a couple of missed writes don't flip a camera to
# "offline" downstream, but a dead worker eventually does (the key expires).
HEARTBEAT_TTL_SECONDS = 15


async def heartbeat_loop(client: Redis, camera_id: str, get_status: Callable[[], str]) -> None:
    """Write `camera:status:<id> = get_status()` every 5s, forever."""
    while True:
        await client.set(f"camera:status:{camera_id}", get_status(), ex=HEARTBEAT_TTL_SECONDS)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
