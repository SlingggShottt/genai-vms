import fakeredis.aioredis
import pytest
from api.api.errors import APIError
from api.api.ratelimit import client_key, limit
from api.settings import RateLimitSettings
from starlette.requests import Request


def _request(redis, *, enabled=True, per_minute=3, forwarded=None, client="10.0.0.9") -> Request:
    from types import SimpleNamespace

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    request = Request({"type": "http", "headers": headers, "client": (client, 1234)})
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(
                ratelimit=RateLimitSettings(
                    _env_file=None, enabled=enabled, login_per_minute=per_minute
                )
            ),
            redis_client=redis,
        )
    )
    return request


async def test_requests_beyond_the_allowance_get_429_with_retry_after():
    redis = fakeredis.aioredis.FakeRedis()
    check = limit("login")
    for _ in range(3):
        await check(_request(redis))
    with pytest.raises(APIError) as caught:
        await check(_request(redis))
    err = caught.value
    assert err.status_code == 429 and err.code == "RATE_LIMITED"
    assert 1 <= int(err.headers["Retry-After"]) <= 60


async def test_each_client_and_each_group_has_its_own_allowance():
    redis = fakeredis.aioredis.FakeRedis()
    for _ in range(3):
        await limit("login")(_request(redis, client="10.0.0.1"))
    await limit("login")(_request(redis, client="10.0.0.2"))  # another client is unaffected
    await limit("search")(_request(redis, client="10.0.0.1"))  # so is another endpoint group


async def test_it_is_off_when_disabled_and_open_when_redis_is_down():
    redis = fakeredis.aioredis.FakeRedis()
    for _ in range(10):
        await limit("login")(_request(redis, enabled=False))

    class Broken:
        async def incr(self, *_):
            raise ConnectionError("redis is down")

    for _ in range(10):
        await limit("login")(_request(Broken()))


def test_the_client_is_the_first_forwarded_address_else_the_peer():
    assert client_key(_request(None, forwarded="203.0.113.5, 10.0.0.1")) == "203.0.113.5"
    assert client_key(_request(None)) == "10.0.0.9"
