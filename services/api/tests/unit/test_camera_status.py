"""Unit tests for the Redis heartbeat status-merge logic (FR-CAM-02). A
fake Redis client (just `mget`), no real Redis needed.
"""

from __future__ import annotations

from api.adapters.camera_status import get_camera_statuses


class _FakeRedis:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self._values.get(key) for key in keys]


async def test_returns_the_heartbeat_value_when_present() -> None:
    redis = _FakeRedis({"camera:status:cam01": "online", "camera:status:cam02": "reconnecting"})
    result = await get_camera_statuses(redis, ["cam01", "cam02"])
    assert result == {"cam01": "online", "cam02": "reconnecting"}


async def test_reports_offline_for_a_missing_key() -> None:
    """No heartbeat is ever written as "offline" — the key just expires (or
    never existed). A missing key must read as offline, not error or drop
    the camera from the result.
    """
    redis = _FakeRedis({})
    result = await get_camera_statuses(redis, ["cam99"])
    assert result == {"cam99": "offline"}


async def test_mixed_online_and_missing_keys() -> None:
    redis = _FakeRedis({"camera:status:cam01": "online"})
    result = await get_camera_statuses(redis, ["cam01", "cam02"])
    assert result == {"cam01": "online", "cam02": "offline"}


async def test_empty_camera_list_returns_empty_dict_without_calling_redis() -> None:
    class _ExplodingRedis:
        async def mget(self, keys: list[str]) -> list[str | None]:
            raise AssertionError("mget should not be called for an empty camera list")

    result = await get_camera_statuses(_ExplodingRedis(), [])
    assert result == {}
