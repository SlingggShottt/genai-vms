"""Redis response cache: the key and the store."""

from __future__ import annotations

import redis.exceptions
from fakeredis import FakeAsyncRedis
from vms_common.llm.cache import KEY_PREFIX, ResponseCache, cache_key
from vms_common.llm.registry import ModelRef

REF = ModelRef(provider="ollama", model="qwen2.5:3b")
MESSAGES = [{"role": "user", "content": "find a red car"}]


def key(**overrides) -> str:
    args = {
        "task": "query_decompose",
        "ref": REF,
        "messages": MESSAGES,
        "response_schema": {"type": "object"},
        "temperature": 0.0,
        "max_tokens": 600,
    } | overrides
    return cache_key(**args)


def test_identical_requests_share_a_key() -> None:
    assert key() == key()
    assert key().startswith(KEY_PREFIX)


def test_dict_ordering_does_not_change_the_key() -> None:
    a = key(response_schema={"type": "object", "required": ["x"], "properties": {}})
    b = key(response_schema={"properties": {}, "required": ["x"], "type": "object"})
    assert a == b


def test_anything_that_could_change_the_answer_changes_the_key() -> None:
    base = key()
    variants = {
        "task": key(task="rerank"),
        "model": key(ref=ModelRef(provider="ollama", model="qwen2.5:7b")),
        "provider": key(ref=ModelRef(provider="gemini", model="qwen2.5:3b")),
        "adapter": key(ref=ModelRef(provider="ollama", model="qwen2.5:3b", adapter="s3://a")),
        "messages": key(messages=[{"role": "user", "content": "find a blue car"}]),
        "image": key(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}
                    ],
                }
            ]
        ),
        "schema": key(response_schema={"type": "object", "required": ["x"]}),
        "no schema": key(response_schema=None),
        "temperature": key(temperature=0.7),
        "max_tokens": key(max_tokens=100),
    }
    assert base not in variants.values()
    assert len(set(variants.values())) == len(variants)


def test_a_different_image_in_the_messages_is_a_different_key() -> None:
    def with_image(b64: str) -> str:
        part = {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        return key(messages=[{"role": "user", "content": [part]}])

    assert with_image("AAAA") == with_image("AAAA")
    assert with_image("AAAA") != with_image("AAAB")


def test_unicode_prompts_hash_fine() -> None:
    assert key(messages=[{"role": "user", "content": "लाल कार ढूंढो 🚗"}])


async def test_set_then_get_round_trips_and_expires(redis_client) -> None:
    cache = ResponseCache(redis_client)
    await cache.set("k", {"text": "hi", "usage": {"prompt_tokens": 1}}, ttl_s=60)
    assert await cache.get("k") == {"text": "hi", "usage": {"prompt_tokens": 1}}
    assert 0 < await redis_client.ttl("k") <= 60


async def test_a_miss_is_none(redis_client) -> None:
    assert await ResponseCache(redis_client).get("absent") is None


async def test_a_corrupt_entry_is_a_miss_not_an_error(redis_client) -> None:
    await redis_client.set("k", "{not json")
    assert await ResponseCache(redis_client).get("k") is None
    await redis_client.set("k", "[1, 2]")  # valid JSON, wrong shape
    assert await ResponseCache(redis_client).get("k") is None


async def test_redis_failures_degrade_to_a_miss_and_a_dropped_write() -> None:
    client = FakeAsyncRedis(decode_responses=True)

    async def boom(*_a, **_k):
        raise redis.exceptions.ConnectionError("down")

    client.get = boom  # type: ignore[method-assign]
    client.set = boom  # type: ignore[method-assign]
    cache = ResponseCache(client)
    assert await cache.get("k") is None
    await cache.set("k", {"text": "x"}, ttl_s=10)  # must not raise
    await client.aclose()
