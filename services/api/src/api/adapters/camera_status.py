"""Merges ingestion's `camera:status:<code>` Redis heartbeats
(services/ingestion/src/ingestion/adapters/heartbeat.py) into a per-camera
status for `GET /cameras/status` (FR-CAM-02).

Only "online" and "reconnecting" are ever written to Redis; ingestion never
writes "offline" — a dead/stopped worker just lets the key expire (15s TTL,
written every 5s). So "key absent" *is* "offline", not a third value a
producer writes.
"""

from __future__ import annotations

from redis.asyncio import Redis

OFFLINE = "offline"


def _status_key(camera_code: str) -> str:
    return f"camera:status:{camera_code}"


async def get_camera_statuses(redis_client: Redis, camera_codes: list[str]) -> dict[str, str]:
    """`{code: "online" | "reconnecting" | "offline"}` for every code given.
    A single `MGET` round trip regardless of camera count.
    """
    if not camera_codes:
        return {}
    keys = [_status_key(code) for code in camera_codes]
    values = await redis_client.mget(keys)
    return {
        code: (value if value is not None else OFFLINE)
        for code, value in zip(camera_codes, values, strict=True)
    }
