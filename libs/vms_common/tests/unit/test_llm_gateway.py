"""LLMGateway policy: fallbacks, validation retries, cache, lease, streaming, metrics.

The provider is a `ScriptedBackend`, so this exercises the real gateway code with no network.
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any

import pytest
import vms_common.llm.gateway as gateway_module
from fakeredis import FakeAsyncRedis
from PIL import Image
from prometheus_client import REGISTRY
from pydantic import BaseModel
from vms_common.config import LLMSettings
from vms_common.llm import (
    GPULeaseTimeoutError,
    ImageInput,
    LLMGateway,
    LLMOutputError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
    ModelRegistry,
    ToolSpec,
)
from vms_common.llm.backend import BackendError, LiteLLMBackend, RawCompletion
from vms_common.llm.cache import ResponseCache
from vms_common.llm.lease import GPULease
from vms_common.llm.testing import ScriptedBackend
from vms_common.llm.types import ChatChunk, ToolCall, Usage

TXT = "ollama:qwen2.5:3b"
VL = "ollama:qwen2.5vl:3b"

RAW_REGISTRY: dict[str, Any] = {
    "tasks": {
        "local_text": {"max_tokens": 50},
        "local_see": {
            "modality": "vision", "max_images": 2, "max_image_edge": 64, "cache_ttl_s": 60,
        },
        "cloud_text": {"cache_ttl_s": 60, "max_tokens": 80, "temperature": 0.0},
        "uncached": {},
        "with_fallback": {"timeout_s": 0.05},
        "local_then_cloud": {},
        "no_retries": {"validation_retries": 0},
    },
    "profiles": {
        "local": {
            "local_text": {"provider": "ollama", "model": "qwen2.5:3b", "num_ctx": 8192},
            "local_see": {"provider": "ollama", "model": "qwen2.5vl:3b"},
            "cloud_text": {"provider": "gemini", "model": "flash"},
            "uncached": {"provider": "gemini", "model": "flash"},
            "with_fallback": {
                "provider": "gemini", "model": "flash", "fallback": ["groq/gpt-oss"],
            },
            "local_then_cloud": {
                "provider": "ollama", "model": "qwen2.5:3b", "fallback": ["gemini/flash"],
            },
            "no_retries": {"provider": "gemini", "model": "flash"},
        },
        "hybrid": {
            "extends": "local",
            "local_text": {"provider": "gemini", "model": "flash"},
        },
        "cloud": {"extends": "hybrid"},
    },
}  # fmt: skip

MSGS = [{"role": "user", "content": "hello"}]


class Verdict(BaseModel):
    verdict: str
    confidence: float


GOOD = '{"verdict": "confirmed", "confidence": 0.9}'


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def jpeg(width: int, height: int, colour: str = "red") -> ImageInput:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="JPEG")
    return ImageInput(data=buffer.getvalue())


class Rig:
    """A gateway wired to scripted backends and an in-memory Redis."""

    def __init__(self, redis: FakeAsyncRedis, *, lease: bool = True, cache: bool = True) -> None:
        self.redis = redis
        self.ollama = ScriptedBackend()
        self.gemini = ScriptedBackend()
        self.groq = ScriptedBackend()
        self.lease = GPULease(redis, node="t", ttl_s=5.0, poll_s=0.02) if lease else None
        self.gateway = LLMGateway(
            ModelRegistry.from_dict(RAW_REGISTRY, profile="local"),
            {"ollama": self.ollama, "gemini": self.gemini, "groq": self.groq},
            lease=self.lease,
            cache=ResponseCache(redis) if cache else None,
            lease_wait_s=0.3,
        )


@pytest.fixture
def rig(redis_client: FakeAsyncRedis) -> Rig:
    return Rig(redis_client)


# --- plain chat ----------------------------------------------------------------------------


async def test_chat_returns_text_with_provenance_and_passes_the_task_settings(rig: Rig) -> None:
    rig.ollama._replies.append("hi there")
    result = await rig.gateway.chat("local_text", MSGS)
    assert (result.text, result.task, result.provider, result.model) == (
        "hi there", "local_text", "ollama", "qwen2.5:3b",
    )  # fmt: skip
    assert (result.attempts, result.fallback_index, result.cached) == (1, 0, False)
    assert result.usage == Usage(prompt_tokens=10, completion_tokens=5)
    assert result.latency_s > 0
    (call,) = rig.ollama.calls
    assert call.messages == [{"role": "user", "content": "hello"}]
    assert (call.temperature, call.max_tokens, call.timeout_s) == (0.0, 50, 120.0)
    assert call.ref.num_ctx == 8192
    assert call.response_format is None and call.tools is None


async def test_messages_may_be_models_or_plain_dicts(rig: Rig) -> None:
    rig.ollama._replies.append("ok")
    await rig.gateway.chat(
        "local_text",
        [Message(role="system", content="be brief"), {"role": "user", "content": "q"}],
    )
    assert [m["role"] for m in rig.ollama.calls[0].messages] == ["system", "user"]


async def test_bad_calls_are_request_errors_before_any_model_is_touched(rig: Rig) -> None:
    with pytest.raises(LLMRequestError, match="unknown task"):
        await rig.gateway.chat("nope", MSGS)
    with pytest.raises(LLMRequestError, match="empty"):
        await rig.gateway.chat("local_text", [])
    with pytest.raises(LLMRequestError, match="cannot be combined"):
        await rig.gateway.chat(
            "local_text", MSGS, response_model=Verdict, tools=[ToolSpec(name="f", description="d")]
        )
    with pytest.raises(LLMRequestError, match="stream=True"):
        await rig.gateway.chat("local_text", MSGS, stream=True, response_model=Verdict)
    assert not rig.ollama.calls and not rig.gemini.calls


async def test_tools_are_sent_in_the_openai_function_shape_and_calls_come_back(rig: Rig) -> None:
    call = ToolCall(id="c1", name="count_objects", arguments={"camera": "cam01"})
    rig.ollama._replies.append(
        RawCompletion(text="", tool_calls=[call], finish_reason="tool_calls")
    )
    spec = ToolSpec(
        name="count_objects",
        description="Count objects",
        parameters={"type": "object", "properties": {"camera": {"type": "string"}}},
    )
    result = await rig.gateway.chat("local_text", MSGS, tools=[spec])
    assert result.tool_calls == [call]
    assert rig.ollama.calls[0].tools == [
        {
            "type": "function",
            "function": {
                "name": "count_objects",
                "description": "Count objects",
                "parameters": spec.parameters,
            },
        }
    ]


async def test_tool_turns_are_forwarded_with_their_ids(rig: Rig) -> None:
    rig.ollama._replies.append("There were 4.")
    call = ToolCall(id="c1", name="count_objects", arguments={"camera": "cam01"})
    await rig.gateway.chat(
        "local_text",
        [
            Message(role="user", content="how many?"),
            Message(role="assistant", tool_calls=[call]),
            Message(role="tool", content="4", tool_call_id="c1", name="count_objects"),
        ],
    )
    wire = rig.ollama.calls[0].messages
    assert wire[1]["tool_calls"] == [
        {
            "id": "c1", "type": "function",
            "function": {"name": "count_objects", "arguments": '{"camera": "cam01"}'},
        }
    ]  # fmt: skip
    assert wire[2] == {
        "role": "tool",
        "content": "4",
        "tool_call_id": "c1",
        "name": "count_objects",
    }


# --- structured output ---------------------------------------------------------------------


async def test_response_model_reply_is_parsed_and_the_schema_goes_to_the_provider(rig: Rig) -> None:
    rig.gemini._replies.append(GOOD)
    result = await rig.gateway.chat("uncached", MSGS, response_model=Verdict)
    assert result.parsed == Verdict(verdict="confirmed", confidence=0.9)
    fmt = rig.gemini.calls[0].response_format
    assert fmt is not None and fmt["json_schema"]["name"] == "Verdict"
    assert set(fmt["json_schema"]["schema"]["required"]) == {"verdict", "confidence"}


async def test_json_in_code_fences_costs_no_retry(rig: Rig) -> None:
    rig.gemini._replies.append(f"Here you go:\n```json\n{GOOD}\n```")
    result = await rig.gateway.chat("uncached", MSGS, response_model=Verdict)
    assert result.parsed.verdict == "confirmed" and result.attempts == 1


async def test_an_invalid_reply_is_shown_its_errors_and_asked_again(rig: Rig) -> None:
    rig.gemini._replies.extend(['{"verdict": "confirmed"}', GOOD])
    before = sample("vms_llm_retries_total", task="uncached")
    result = await rig.gateway.chat("uncached", MSGS, response_model=Verdict)
    assert result.parsed.confidence == 0.9
    assert result.attempts == 2
    retry = rig.gemini.calls[1].messages
    assert retry[:1] == [{"role": "user", "content": "hello"}]
    assert retry[1] == {"role": "assistant", "content": '{"verdict": "confirmed"}'}
    assert retry[2]["role"] == "user" and "confidence" in retry[2]["content"]
    assert sample("vms_llm_retries_total", task="uncached") == before + 1
    assert rig.gemini.calls[0].messages == [{"role": "user", "content": "hello"}]  # not mutated


async def test_output_that_never_validates_stops_after_the_retry_budget(rig: Rig) -> None:
    rig.gemini._default = "I refuse to answer in JSON."
    with pytest.raises(LLMOutputError, match="3 replies") as caught:
        await rig.gateway.chat("uncached", MSGS, response_model=Verdict)
    assert len(rig.gemini.calls) == 3  # 1 + validation_retries (2)
    assert caught.value.last_text == "I refuse to answer in JSON."
    assert not isinstance(caught.value, LLMUnavailableError)


async def test_validation_retries_zero_means_one_try(rig: Rig) -> None:
    rig.gemini._default = "nope"
    with pytest.raises(LLMOutputError):
        await rig.gateway.chat("no_retries", MSGS, response_model=Verdict)
    assert len(rig.gemini.calls) == 1


async def test_without_a_response_model_a_malformed_reply_is_just_text(rig: Rig) -> None:
    rig.gemini._replies.append("not json at all")
    result = await rig.gateway.chat("uncached", MSGS)
    assert (result.text, result.parsed, result.attempts) == ("not json at all", None, 1)


async def test_every_attempt_counts_toward_token_metrics(rig: Rig) -> None:
    rig.gemini._replies.extend(["bad", GOOD])  # 2 calls x (10 prompt + 5 completion)
    prompt = sample("vms_llm_tokens_total", provider="gemini", task="uncached", kind="prompt")
    completion = sample(
        "vms_llm_tokens_total", provider="gemini", task="uncached", kind="completion"
    )
    await rig.gateway.chat("uncached", MSGS, response_model=Verdict)
    assert (
        sample("vms_llm_tokens_total", provider="gemini", task="uncached", kind="prompt")
        == prompt + 20
    )
    assert (
        sample("vms_llm_tokens_total", provider="gemini", task="uncached", kind="completion")
        == completion + 10
    )


# --- fallbacks -----------------------------------------------------------------------------


async def test_a_failing_primary_falls_back_to_the_next_model(rig: Rig) -> None:
    rig.gemini._replies.append(BackendError("rate_limit", "429 quota"))
    rig.groq._replies.append("from groq")
    before = sample("vms_llm_fallbacks_total", task="with_fallback")
    result = await rig.gateway.chat("with_fallback", MSGS)
    assert (result.text, result.provider, result.model) == ("from groq", "groq", "gpt-oss")
    assert (result.fallback_index, result.attempts) == (1, 2)
    assert sample("vms_llm_fallbacks_total", task="with_fallback") == before + 1


@pytest.mark.parametrize(
    "kind", ["timeout", "rate_limit", "auth", "not_found", "bad_request", "unavailable"]
)
async def test_every_kind_of_provider_failure_moves_on_to_the_fallback(rig: Rig, kind: str) -> None:
    rig.gemini._replies.append(BackendError(kind, "boom"))  # type: ignore[arg-type]
    rig.groq._replies.append("rescued")
    assert (await rig.gateway.chat("with_fallback", MSGS)).text == "rescued"


async def test_a_provider_that_ignores_its_timeout_is_cut_off_and_falls_back(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway_module, "_TIMEOUT_SLACK_S", 0.0)

    async def hang(_call):
        await asyncio.sleep(5)

    rig.gemini._replies.append(hang)
    rig.groq._replies.append("quick")
    result = await rig.gateway.chat("with_fallback", MSGS)  # task timeout_s = 0.05
    assert result.text == "quick" and result.fallback_index == 1
    assert (
        sample(
            "vms_llm_request_seconds_count",
            provider="gemini",
            task="with_fallback",
            status="timeout",
        )
        >= 1
    )


async def test_when_every_model_fails_the_error_follows_the_primary_and_lists_all(rig: Rig) -> None:
    rig.gemini._replies.append(BackendError("unavailable", "gemini down"))
    rig.groq._replies.append(BackendError("rate_limit", "groq 429"))
    with pytest.raises(LLMUnavailableError, match="every model for task 'with_fallback'") as caught:
        await rig.gateway.chat("with_fallback", MSGS)
    assert len(caught.value.failures) == 2
    assert "gemini/flash" in caught.value.failures[0] and "gemini down" in caught.value.failures[0]
    assert "groq/gpt-oss" in caught.value.failures[1]
    assert not isinstance(caught.value, LLMTimeoutError)


async def test_a_timing_out_primary_surfaces_as_a_timeout_error(rig: Rig) -> None:
    rig.gemini._replies.append(BackendError("timeout", "slow"))
    rig.groq._replies.append(BackendError("unavailable", "also down"))
    with pytest.raises(LLMTimeoutError):
        await rig.gateway.chat("with_fallback", MSGS)


async def test_invalid_output_from_the_primary_falls_back_and_a_valid_one_wins(rig: Rig) -> None:
    rig.gemini._default = "garbage"
    rig.groq._replies.append(GOOD)
    result = await rig.gateway.chat("with_fallback", MSGS, response_model=Verdict)
    assert result.parsed.verdict == "confirmed" and result.fallback_index == 1
    assert result.attempts == 4  # 3 rejected replies from gemini + 1 good one from groq


async def test_invalid_output_everywhere_is_an_output_error_not_an_outage(rig: Rig) -> None:
    rig.gemini._default = "garbage"
    rig.groq._default = "garbage too"
    with pytest.raises(LLMOutputError) as caught:
        await rig.gateway.chat("with_fallback", MSGS, response_model=Verdict)
    assert caught.value.last_text == "garbage"
    assert len(caught.value.failures) == 2


async def test_a_provider_without_a_backend_counts_as_unavailable(rig: Rig) -> None:
    gateway = LLMGateway(rig.gateway.registry, {"gemini": rig.gemini}, lease=rig.lease)
    rig.gemini._replies.append("from gemini")
    with pytest.raises(LLMUnavailableError, match="no backend registered for provider 'ollama'"):
        await gateway.chat("local_text", MSGS)
    assert (await gateway.chat("local_then_cloud", MSGS)).text == "from gemini"  # fell back


async def test_a_backend_registered_later_serves_its_provider(rig: Rig) -> None:
    registry = ModelRegistry.from_dict(RAW_REGISTRY, profile="local")
    gateway = LLMGateway(registry, {})
    late = ScriptedBackend("late hello")
    gateway.register_backend("gemini", late)
    assert (await gateway.chat("uncached", MSGS)).text == "late hello"


async def test_request_errors_are_not_swallowed_by_the_fallback_chain(rig: Rig) -> None:
    with pytest.raises(LLMRequestError):
        await rig.gateway.vision("local_see", "p", [jpeg(8, 8)] * 3)
    assert not rig.ollama.calls and not rig.gemini.calls


# --- response cache ------------------------------------------------------------------------


async def test_an_identical_second_call_is_served_from_the_cache(rig: Rig) -> None:
    rig.gemini._replies.append(GOOD)
    first = await rig.gateway.chat("cloud_text", MSGS, response_model=Verdict)
    second = await rig.gateway.chat("cloud_text", MSGS, response_model=Verdict)
    assert len(rig.gemini.calls) == 1
    assert (first.cached, second.cached) == (False, True)
    assert second.parsed == first.parsed
    assert (second.attempts, second.usage) == (0, first.usage)
    assert (second.provider, second.model) == ("gemini", "flash")


async def test_cache_hits_and_misses_are_counted(rig: Rig) -> None:
    rig.gemini._replies.append("x")
    hit = sample("vms_llm_cache_total", task="cloud_text", result="hit")
    miss = sample("vms_llm_cache_total", task="cloud_text", result="miss")
    await rig.gateway.chat("cloud_text", MSGS)
    await rig.gateway.chat("cloud_text", MSGS)
    assert sample("vms_llm_cache_total", task="cloud_text", result="miss") == miss + 1
    assert sample("vms_llm_cache_total", task="cloud_text", result="hit") == hit + 1


async def test_a_different_request_is_a_miss(rig: Rig) -> None:
    rig.gemini._replies.extend(["one", "two", GOOD])
    await rig.gateway.chat("cloud_text", MSGS)
    other = await rig.gateway.chat("cloud_text", [{"role": "user", "content": "different"}])
    assert other.text == "two" and not other.cached
    structured = await rig.gateway.chat("cloud_text", MSGS, response_model=Verdict)
    assert structured.parsed and not structured.cached  # same prompt, different schema → miss


async def test_tasks_without_a_cache_ttl_are_never_cached(rig: Rig) -> None:
    rig.gemini._replies.extend(["a", "b"])
    assert (await rig.gateway.chat("uncached", MSGS)).text == "a"
    assert (await rig.gateway.chat("uncached", MSGS)).text == "b"


async def test_tasks_without_a_cache_ttl_never_touch_redis_at_all(rig: Rig) -> None:
    rig.gemini._replies.extend(["a", "b"])
    lookups = sample("vms_llm_cache_total", task="uncached", result="miss")
    await rig.gateway.chat("uncached", MSGS)
    await rig.gateway.chat("uncached", MSGS)
    assert [k async for k in rig.redis.scan_iter("vms:llm:cache:*")] == []
    assert sample("vms_llm_cache_total", task="uncached", result="miss") == lookups


async def test_tool_calls_are_never_cached(rig: Rig) -> None:
    rig.gemini._replies.extend(["a", "b"])
    spec = ToolSpec(name="f", description="d")
    assert (await rig.gateway.chat("cloud_text", MSGS, tools=[spec])).text == "a"
    assert (await rig.gateway.chat("cloud_text", MSGS, tools=[spec])).text == "b"


async def test_failed_calls_are_not_cached(rig: Rig) -> None:
    rig.gemini._replies.extend(["bad", "bad", "bad", GOOD])
    with pytest.raises(LLMOutputError):
        await rig.gateway.chat("cloud_text", MSGS, response_model=Verdict)
    assert (await rig.gateway.chat("cloud_text", MSGS, response_model=Verdict)).parsed


async def test_a_cached_entry_that_no_longer_validates_is_ignored_and_replaced(rig: Rig) -> None:
    rig.gemini._replies.extend([GOOD, GOOD])
    await rig.gateway.chat("cloud_text", MSGS, response_model=Verdict)
    (key,) = [k async for k in rig.redis.scan_iter("vms:llm:cache:*")]
    await rig.redis.set(key, '{"text": "{\\"verdict\\": 1}", "usage": {}}')  # no longer valid

    healed = await rig.gateway.chat("cloud_text", MSGS, response_model=Verdict)
    assert not healed.cached  # the stale entry was not served ...
    assert len(rig.gemini.calls) == 2  # ... the model was asked again ...
    assert (await rig.gateway.chat("cloud_text", MSGS, response_model=Verdict)).cached  # ... and
    assert len(rig.gemini.calls) == 2  # the fresh answer replaced it


async def test_a_redis_outage_costs_the_cache_not_the_call() -> None:
    client = FakeAsyncRedis(decode_responses=True)
    rig = Rig(client, lease=False)

    async def down(*_a, **_k):
        raise ConnectionError("redis down")

    client.get = down  # type: ignore[method-assign]
    client.set = down  # type: ignore[method-assign]
    rig.gemini._replies.extend(["a", "b"])
    assert (await rig.gateway.chat("cloud_text", MSGS)).text == "a"
    assert (await rig.gateway.chat("cloud_text", MSGS)).text == "b"
    await client.aclose()


async def test_a_gateway_without_a_cache_just_calls_the_model_every_time(redis_client) -> None:
    rig = Rig(redis_client, cache=False)
    rig.gemini._replies.extend(["a", "b"])
    assert (await rig.gateway.chat("cloud_text", MSGS)).text == "a"
    assert (await rig.gateway.chat("cloud_text", MSGS)).text == "b"


# --- vision --------------------------------------------------------------------------------


async def test_images_ride_on_the_last_user_message_as_data_urls(rig: Rig) -> None:
    rig.ollama._replies.append(GOOD)
    image = jpeg(40, 30)
    await rig.gateway.vision(
        "local_see", "is this real?", [image], response_model=Verdict, system="be strict"
    )
    wire = rig.ollama.calls[0].messages
    assert wire[0] == {"role": "system", "content": "be strict"}
    parts = wire[1]["content"]
    assert parts[0] == {"type": "text", "text": "is this real?"}
    assert parts[1]["type"] == "image_url"
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == image.data  # small image: untouched


async def test_oversized_images_are_shrunk_before_they_reach_the_model(rig: Rig) -> None:
    rig.ollama._replies.append("ok")
    await rig.gateway.vision("local_see", "p", [jpeg(640, 480)])
    url = rig.ollama.calls[0].messages[0]["content"][1]["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as sent:
        assert max(sent.size) == 64  # the task's max_image_edge


async def test_the_image_count_cap_is_enforced(rig: Rig) -> None:
    with pytest.raises(LLMRequestError, match="3 images exceed this task's cap of 2"):
        await rig.gateway.vision("local_see", "p", [jpeg(8, 8)] * 3)
    with pytest.raises(LLMRequestError, match="at least one image"):
        await rig.gateway.vision("local_see", "p", [])


async def test_vision_on_a_text_task_is_a_request_error(rig: Rig) -> None:
    with pytest.raises(LLMRequestError, match="text-only; use chat"):
        await rig.gateway.vision("local_text", "p", [jpeg(8, 8)])


async def test_vision_replies_are_cached_per_image(rig: Rig) -> None:
    rig.ollama._replies.extend(["red car", "blue car"])
    red, blue = jpeg(32, 32, "red"), jpeg(32, 32, "blue")
    assert (await rig.gateway.vision("local_see", "what colour?", [red])).text == "red car"
    again = await rig.gateway.vision("local_see", "what colour?", [red])
    assert again.cached and again.text == "red car"
    other = await rig.gateway.vision("local_see", "what colour?", [blue])
    assert other.text == "blue car" and not other.cached


# --- GPU lease -----------------------------------------------------------------------------


async def test_a_local_model_runs_under_the_lease_and_releases_it(rig: Rig) -> None:
    seen: list[str | None] = []

    async def probe(_call):
        seen.append(await rig.lease.current_family())
        return "ok"

    rig.ollama._replies.append(probe)
    await rig.gateway.chat("local_text", MSGS)
    assert seen == [TXT]
    assert await rig.lease.current_family() is None
    assert await rig.redis.get("gpu:loaded:t") == TXT


async def test_cloud_models_never_touch_the_gpu_lease(rig: Rig) -> None:
    seen: list[str | None] = []

    async def probe(_call):
        seen.append(await rig.lease.current_family())
        return "ok"

    rig.gemini._replies.append(probe)
    await rig.gateway.chat("uncached", MSGS)
    assert seen == [None]
    assert await rig.redis.get("gpu:loaded:t") is None


async def test_switching_model_families_unloads_the_one_it_displaces(rig: Rig) -> None:
    rig.ollama._replies.extend(["t1", "t2", "v1", "t3"])
    await rig.gateway.chat("local_text", MSGS)
    await rig.gateway.chat("local_text", MSGS)  # same family: nothing to unload
    assert rig.ollama.unloaded == []
    await rig.gateway.vision("local_see", "p", [jpeg(8, 8)])
    assert rig.ollama.unloaded == [TXT]
    await rig.gateway.chat("local_text", MSGS)
    assert rig.ollama.unloaded == [TXT, VL]


async def test_a_failing_unload_does_not_fail_the_call(rig: Rig) -> None:
    async def broken_unload(_family: str) -> None:
        raise RuntimeError("ollama is unreachable")

    rig.ollama.unload = broken_unload  # type: ignore[method-assign]
    rig.ollama._replies.extend(["t", "v"])
    await rig.gateway.chat("local_text", MSGS)
    result = await rig.gateway.vision("local_see", "p", [jpeg(8, 8)])
    assert result.text == "v"


async def test_a_busy_gpu_falls_back_to_the_cloud_model(rig: Rig) -> None:
    rig.gemini._replies.append("cloud answer")
    async with rig.lease.hold(VL, wait_s=1):  # another family holds the GPU
        result = await rig.gateway.chat("local_then_cloud", MSGS)  # lease_wait_s = 0.3
    assert (result.text, result.provider, result.fallback_index) == ("cloud answer", "gemini", 1)
    assert not rig.ollama.calls  # the local model was never started behind the lease's back


async def test_a_busy_gpu_with_no_fallback_is_a_lease_timeout(rig: Rig) -> None:
    async with rig.lease.hold(VL, wait_s=1):
        with pytest.raises(GPULeaseTimeoutError, match="held by"):
            await rig.gateway.chat("local_text", MSGS)


async def test_the_lease_is_released_when_the_model_call_fails(rig: Rig) -> None:
    rig.ollama._replies.append(BackendError("unavailable", "ollama crashed"))
    with pytest.raises(LLMUnavailableError):
        await rig.gateway.chat("local_text", MSGS)
    assert await rig.lease.current_family() is None


async def test_validation_retries_stay_inside_one_lease_hold(rig: Rig) -> None:
    holds = 0
    real_hold = rig.lease.hold

    def counting_hold(*args, **kwargs):
        nonlocal holds
        holds += 1
        return real_hold(*args, **kwargs)

    rig.lease.hold = counting_hold  # type: ignore[method-assign]
    rig.ollama._replies.extend(["bad", GOOD])
    await rig.gateway.chat("local_text", MSGS, response_model=Verdict)
    assert holds == 1 and len(rig.ollama.calls) == 2


async def test_two_families_called_at_once_never_share_the_gpu(redis_client) -> None:
    rig = Rig(redis_client)
    rig.gateway._lease_wait_s = 10
    active = {TXT: 0, VL: 0}
    overlaps: list[str] = []

    async def work(call):
        family = call.ref.family
        active[family] += 1
        if any(n for f, n in active.items() if f != family):
            overlaps.append(family)
        await asyncio.sleep(0.02)
        active[family] -= 1
        return "ok"

    rig.ollama._default = work
    jobs = [
        rig.gateway.chat("local_text", [{"role": "user", "content": f"t{i}"}]) for i in range(6)
    ]
    jobs += [rig.gateway.vision("local_see", f"v{i}", [jpeg(8 + i, 8)]) for i in range(6)]
    results = await asyncio.gather(*jobs)
    assert all(r.text == "ok" for r in results)
    assert overlaps == []


async def test_a_gateway_without_a_lease_still_runs_local_models(redis_client) -> None:
    rig = Rig(redis_client, lease=False)
    rig.ollama._replies.extend(["a", "b"])
    assert (await rig.gateway.chat("local_text", MSGS)).text == "a"
    assert (await rig.gateway.chat("local_text", MSGS)).text == "b"


async def test_a_redis_outage_blocks_local_models_but_cloud_fallbacks_still_answer() -> None:
    client = FakeAsyncRedis(decode_responses=True)
    rig = Rig(client)

    async def down(*_a, **_k):
        raise ConnectionError("redis down")

    rig.lease._acquire_script = down  # type: ignore[assignment]
    rig.gemini._replies.append("cloud")
    result = await rig.gateway.chat("local_then_cloud", MSGS)
    assert result.text == "cloud" and not rig.ollama.calls
    with pytest.raises(LLMUnavailableError, match="GPU lease unavailable"):
        await rig.gateway.chat("local_text", MSGS)
    await client.aclose()


# --- streaming -----------------------------------------------------------------------------


FINAL = ChatChunk(finish_reason="stop", usage=Usage(prompt_tokens=7, completion_tokens=3))


async def test_streaming_yields_chunks_in_order_and_holds_the_lease_meanwhile(rig: Rig) -> None:
    rig.ollama._replies.append(["Hel", "lo ", "world", FINAL])
    chunks: list[ChatChunk] = []
    families: list[str | None] = []
    stream = await rig.gateway.chat("local_text", MSGS, stream=True)
    async for chunk in stream:
        chunks.append(chunk)
        families.append(await rig.lease.current_family())
    assert "".join(c.delta for c in chunks) == "Hello world"
    assert chunks[-1].usage == Usage(prompt_tokens=7, completion_tokens=3)
    assert set(families) == {TXT}
    assert await rig.lease.current_family() is None
    assert rig.ollama.calls[0].streamed is True


async def test_stream_tokens_and_latency_are_recorded(rig: Rig) -> None:
    rig.gemini._replies.append(["a", FINAL])
    seconds = sample(
        "vms_llm_request_seconds_count", provider="gemini", task="uncached", status="ok"
    )
    tokens = sample("vms_llm_tokens_total", provider="gemini", task="uncached", kind="prompt")
    async for _ in await rig.gateway.chat("uncached", MSGS, stream=True):
        pass
    assert (
        sample("vms_llm_request_seconds_count", provider="gemini", task="uncached", status="ok")
        == seconds + 1
    )
    assert (
        sample("vms_llm_tokens_total", provider="gemini", task="uncached", kind="prompt")
        == tokens + 7
    )


async def test_a_stream_that_fails_before_any_output_falls_back(rig: Rig) -> None:
    rig.gemini._replies.append(BackendError("rate_limit", "429"))
    rig.groq._replies.append(["from ", "groq", FINAL])
    stream = await rig.gateway.chat("with_fallback", MSGS, stream=True)
    assert "".join([c.delta async for c in stream]) == "from groq"


async def test_a_stream_that_dies_midway_raises_and_does_not_splice_in_another_model(
    rig: Rig,
) -> None:
    rig.gemini._replies.append(["partial ", BackendError("unavailable", "connection dropped")])
    rig.groq._replies.append(["never used"])
    received: list[str] = []
    with pytest.raises(LLMUnavailableError, match="connection dropped"):
        async for chunk in await rig.gateway.chat("with_fallback", MSGS, stream=True):
            received.append(chunk.delta)
    assert received == ["partial "]
    assert not rig.groq.calls


async def test_a_stalled_stream_is_cut_off(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway_module, "_TIMEOUT_SLACK_S", 0.0)
    rig.gemini._replies.append([5])  # nothing for 5 s; the task allows 0.05 s of silence
    rig.groq._replies.append(["recovered", FINAL])
    stream = await rig.gateway.chat("with_fallback", MSGS, stream=True)
    assert "".join([c.delta async for c in stream]) == "recovered"


async def test_every_stream_failing_raises_with_all_failures(rig: Rig) -> None:
    rig.gemini._replies.append(BackendError("unavailable", "down"))
    rig.groq._replies.append(BackendError("unavailable", "also down"))
    with pytest.raises(LLMUnavailableError) as caught:
        async for _ in await rig.gateway.chat("with_fallback", MSGS, stream=True):
            pass
    assert len(caught.value.failures) == 2


async def test_abandoning_a_stream_releases_the_lease(rig: Rig) -> None:
    rig.ollama._replies.append(["a", "b", "c", FINAL])
    stream = await rig.gateway.chat("local_text", MSGS, stream=True)
    iterator = stream.__aiter__()
    first = await iterator.__anext__()
    assert first.delta == "a" and await rig.lease.current_family() == TXT
    await iterator.aclose()  # type: ignore[attr-defined]
    assert await rig.lease.current_family() is None


async def test_abandoning_a_stream_closes_the_providers_stream_too(rig: Rig) -> None:
    closed: list[bool] = []

    async def stream(*_args: Any, **_kwargs: Any):
        try:
            for word in ("a", "b", "c"):
                yield ChatChunk(delta=word)
        finally:
            closed.append(True)  # what releases the provider's HTTP connection

    rig.ollama.stream = stream  # type: ignore[method-assign]
    iterator = (await rig.gateway.chat("local_text", MSGS, stream=True)).__aiter__()
    await iterator.__anext__()
    assert closed == []
    await iterator.aclose()  # type: ignore[attr-defined]
    assert closed == [True]


async def test_tool_calls_arrive_on_the_final_stream_chunk(rig: Rig) -> None:
    call = ToolCall(id="c1", name="f", arguments={"a": 1})
    rig.ollama._replies.append([ChatChunk(tool_calls=[call], finish_reason="tool_calls")])
    chunks = [
        c
        async for c in await rig.gateway.chat(
            "local_text", MSGS, stream=True, tools=[ToolSpec(name="f", description="d")]
        )
    ]
    assert chunks[-1].tool_calls == [call]
    assert rig.ollama.calls[0].tools is not None


# --- metrics -------------------------------------------------------------------------------


async def test_request_latency_is_labelled_with_the_outcome(rig: Rig) -> None:
    ok = sample("vms_llm_request_seconds_count", provider="gemini", task="uncached", status="ok")
    limited = sample(
        "vms_llm_request_seconds_count", provider="gemini", task="uncached", status="rate_limit"
    )
    rig.gemini._replies.extend(["fine", BackendError("rate_limit", "429")])
    await rig.gateway.chat("uncached", MSGS)
    with pytest.raises(LLMUnavailableError):
        await rig.gateway.chat("uncached", MSGS)
    assert (
        sample("vms_llm_request_seconds_count", provider="gemini", task="uncached", status="ok")
        == ok + 1
    )
    assert (
        sample(
            "vms_llm_request_seconds_count", provider="gemini", task="uncached", status="rate_limit"
        )
        == limited + 1
    )


# --- construction & profile switch ---------------------------------------------------------


async def test_the_profile_setting_switches_every_task_with_no_code_change(redis_client) -> None:
    def build(profile: str) -> LLMGateway:
        settings = LLMSettings(_env_file=None, profile=profile, models_path="config/models.yaml")
        return LLMGateway.from_settings(settings, redis=redis_client)

    local, hybrid, cloud = build("local"), build("hybrid"), build("cloud")
    assert (local.profile, hybrid.profile, cloud.profile) == ("local", "hybrid", "cloud")
    provider = lambda gw, task: gw.registry.task(task).primary.provider  # noqa: E731
    assert [provider(g, "rerank") for g in (local, hybrid, cloud)] == ["ollama", "gemini", "gemini"]
    assert [provider(g, "event_verify") for g in (local, hybrid, cloud)] == [
        "ollama", "ollama", "gemini",
    ]  # fmt: skip


def _spy_on_close(client: FakeAsyncRedis) -> list[bool]:
    closed: list[bool] = []
    real = client.aclose

    async def spy() -> None:
        closed.append(True)
        await real()

    client.aclose = spy  # type: ignore[method-assign]
    return closed


async def test_from_settings_wires_litellm_for_four_providers_and_leaves_hf_local_open(
    redis_client,
) -> None:
    closed = _spy_on_close(redis_client)
    gateway = LLMGateway.from_settings(LLMSettings(_env_file=None), redis=redis_client)
    assert set(gateway._backends) == {"ollama", "gemini", "groq", "openrouter"}
    assert all(isinstance(b, LiteLLMBackend) for b in gateway._backends.values())
    assert gateway._lease is not None and gateway._cache is not None
    await gateway.aclose()
    assert closed == []  # a client the caller lent us is the caller's to close


async def test_a_gateway_closes_a_redis_client_it_created(monkeypatch: pytest.MonkeyPatch) -> None:
    created = FakeAsyncRedis(decode_responses=True)
    closed = _spy_on_close(created)
    monkeypatch.setattr(gateway_module, "get_redis_client", lambda _settings=None: created)
    gateway = LLMGateway.from_settings(LLMSettings(_env_file=None))
    await gateway.aclose()
    assert closed == [True]
