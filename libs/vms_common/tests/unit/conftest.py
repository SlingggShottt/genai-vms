"""Fixtures shared by the vms_common unit tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fakeredis import FakeAsyncRedis


@pytest.fixture
async def redis_client() -> AsyncIterator[FakeAsyncRedis]:
    """An in-memory Redis that runs Lua and `TIME`, like the real one (the GPU lease needs both).

    The same behaviour is re-checked against a real Redis in tests/integration/test_llm_lease.py.
    """
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()
