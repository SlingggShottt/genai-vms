"""LiteLLMBackend against a fake Ollama on localhost: the real litellm, a real HTTP round trip,
no internet. Pins down what we send, how replies and errors are read, and streaming.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from pydantic import BaseModel
from vms_common.config import LLMSettings
from vms_common.llm import ImageInput, LLMGateway, ModelRegistry
from vms_common.llm.backend import BackendError, LiteLLMBackend
from vms_common.llm.registry import ModelRef

# (status, body, delay_s). A list body is streamed as NDJSON, a dict as one JSON document.
Reply = tuple[int, Any, float]


@dataclass
class FakeOllama:
    url: str
    requests: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    handler: Callable[[str, dict[str, Any]], Reply] = lambda _p, _b: (200, {}, 0.0)


@pytest.fixture
def ollama() -> Iterator[FakeOllama]:
    fake = FakeOllama(url="")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"  # one request per connection: streams end on close

        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            fake.requests.append((self.path, body))
            status, payload, delay = fake.handler(self.path, body)
            time.sleep(delay)
            # Real Ollama echoes the model it was asked for; litellm prices a call by that name.
            for doc in payload if isinstance(payload, list) else [payload]:
                if isinstance(doc, dict) and "model" in doc and "model" in body:
                    doc["model"] = body["model"]
            if isinstance(payload, list):
                data = b"".join(json.dumps(line).encode() + b"\n" for line in payload)
                content_type = "application/x-ndjson"
            else:
                data = json.dumps(payload).encode()
                content_type = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fake
    server.shutdown()
    server.server_close()


def chat_reply(content: str = "ok", **extra: Any) -> dict[str, Any]:
    return {
        "model": "m",
        "created_at": "2026-10-01T00:00:00Z",
        "message": {"role": "assistant", "content": content, **extra},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 11,
        "eval_count": 5,
    }


def backend_for(fake: FakeOllama, **settings: Any) -> LiteLLMBackend:
    return LiteLLMBackend(LLMSettings(_env_file=None, ollama_url=fake.url, **settings))


VL = ModelRef(provider="ollama", model="qwen2.5vl:3b", num_ctx=6144, keep_alive="2m")
TXT = ModelRef(provider="ollama", model="qwen2.5:3b")
SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "R",
        "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        "strict": True,
    },
}


async def complete(backend: LiteLLMBackend, ref: ModelRef = TXT, **kw: Any):
    args = {
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.0,
        "max_tokens": 64,
        "timeout_s": 5.0,
        "response_format": None,
        "tools": None,
    } | kw
    return await backend.complete(ref, **args)


# --- the request we send -------------------------------------------------------------------


async def test_the_request_uses_ollamas_native_chat_api_with_options_and_a_json_schema(
    ollama: FakeOllama,
) -> None:
    ollama.handler = lambda _p, _b: (200, chat_reply('{"ok": true}'), 0)
    image = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    await complete(
        backend_for(ollama),
        VL,
        messages=[
            {"role": "system", "content": "be strict"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "image_url": {"url": image}},
                ],
            },
        ],
        response_format=SCHEMA,
        temperature=0.2,
        max_tokens=77,
    )
    ((path, body),) = ollama.requests
    assert path == "/api/chat"
    assert body["model"] == "qwen2.5vl:3b"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0.2, "num_predict": 77, "num_ctx": 6144}
    assert body["keep_alive"] == "2m"
    assert body["format"] == SCHEMA["json_schema"]["schema"]  # grammar-constrained decoding
    system = body["messages"][0]
    assert (system["role"], system["content"]) == ("system", "be strict")  # litellm adds images: []
    assert body["messages"][1]["content"] == "what is this?"
    assert body["messages"][1]["images"] == ["/9j/4AAQSkZJRg=="]  # base64 without the data: URL


async def test_options_that_are_not_set_are_not_sent(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (200, chat_reply(), 0)
    await complete(backend_for(ollama), TXT, max_tokens=None)
    (_, body) = ollama.requests[0]
    assert "num_ctx" not in body["options"] and "num_predict" not in body["options"]
    assert "keep_alive" not in body and "format" not in body and "tools" not in body


async def test_tools_are_forwarded(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (200, chat_reply(), 0)
    tool = {
        "type": "function",
        "function": {"name": "count", "description": "d", "parameters": {"type": "object"}},
    }
    await complete(backend_for(ollama), tools=[tool])
    assert ollama.requests[0][1]["tools"] == [tool]


async def test_the_ollama_host_comes_from_settings_not_the_code(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (200, chat_reply(), 0)
    host, port = ollama.url.removeprefix("http://").split(":")
    backend = LiteLLMBackend(LLMSettings(_env_file=None, genai_host=host))  # no ollama_url
    assert backend._settings.effective_ollama_url == f"http://{host}:11434"
    other = LiteLLMBackend(LLMSettings(_env_file=None, ollama_url=f"http://{host}:{port}"))
    await complete(other)
    assert len(ollama.requests) == 1


async def test_litellm_never_asks_the_ollama_server_about_the_model(ollama: FakeOllama) -> None:
    # Unregistered, litellm POSTs /api/show (synchronously!) while pricing a call.
    ollama.handler = lambda path, _b: (200, chat_reply() if path == "/api/chat" else {}, 0)
    backend = backend_for(ollama)
    for _ in range(3):
        await complete(backend, ModelRef(provider="ollama", model="never-seen-before:7b"))
    async for _ in backend.stream(
        TXT, [{"role": "user", "content": "hi"}],
        temperature=0.0, max_tokens=None, timeout_s=5, tools=None,
    ):  # fmt: skip
        pass
    await asyncio.sleep(0.5)  # litellm prices calls on a background worker: let it misbehave
    assert {path for path, _body in ollama.requests} == {"/api/chat"}


# --- the reply we read ---------------------------------------------------------------------


async def test_text_usage_and_finish_reason_are_read_from_the_reply(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (200, chat_reply("hello there"), 0)
    raw = await complete(backend_for(ollama))
    assert raw.text == "hello there"
    assert (raw.usage.prompt_tokens, raw.usage.completion_tokens) == (11, 5)
    assert raw.finish_reason == "stop"
    assert raw.tool_calls == []


async def test_tool_calls_are_parsed_with_generated_ids(ollama: FakeOllama) -> None:
    calls = [
        {"function": {"name": "count_objects", "arguments": {"camera": "cam01", "cls": "person"}}},
        {"function": {"name": "search", "arguments": {"q": "red car"}}},
    ]
    ollama.handler = lambda _p, _b: (200, chat_reply("", tool_calls=calls), 0)
    raw = await complete(backend_for(ollama))
    assert [(c.name, c.arguments) for c in raw.tool_calls] == [
        ("count_objects", {"camera": "cam01", "cls": "person"}),
        ("search", {"q": "red car"}),
    ]
    assert all(c.id for c in raw.tool_calls) and len({c.id for c in raw.tool_calls}) == 2


# --- failures ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind"),
    [(500, "unavailable"), (503, "unavailable"), (404, "not_found"), (400, "bad_request")],
)
async def test_http_errors_are_classified(ollama: FakeOllama, status: int, kind: str) -> None:
    ollama.handler = lambda _p, _b: (status, {"error": "model 'x' not found"}, 0)
    with pytest.raises(BackendError) as caught:
        await complete(backend_for(ollama))
    assert caught.value.kind == kind


async def test_rate_limiting_is_classified(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (429, {"error": "too many requests"}, 0)
    with pytest.raises(BackendError) as caught:
        await complete(backend_for(ollama))
    assert caught.value.kind == "rate_limit"


async def test_a_dead_server_is_unavailable(ollama: FakeOllama) -> None:
    backend = LiteLLMBackend(LLMSettings(_env_file=None, ollama_url="http://127.0.0.1:1"))
    with pytest.raises(BackendError) as caught:
        await complete(backend)
    assert caught.value.kind == "unavailable"


async def test_a_slow_server_hits_the_timeout(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (200, chat_reply(), 1.5)
    started = time.monotonic()
    with pytest.raises(BackendError) as caught:
        await complete(backend_for(ollama), timeout_s=0.3)
    assert caught.value.kind == "timeout"
    assert time.monotonic() - started < 1.2


async def test_error_messages_are_short_and_name_the_exception(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (500, {"error": "x" * 5000}, 0)
    with pytest.raises(BackendError) as caught:
        await complete(backend_for(ollama))
    assert len(str(caught.value)) < 400


@pytest.mark.parametrize("provider", ["gemini", "groq", "openrouter"])
async def test_a_cloud_model_without_its_key_fails_before_any_network_call(
    ollama: FakeOllama, provider: str
) -> None:
    backend = backend_for(ollama)
    with pytest.raises(BackendError, match=f"{provider.upper()}_API_KEY is not set") as caught:
        await complete(backend, ModelRef(provider=provider, model="m"))  # type: ignore[arg-type]
    assert caught.value.kind == "auth"
    assert ollama.requests == []


async def test_the_backend_refuses_providers_it_does_not_serve() -> None:
    backend = LiteLLMBackend(LLMSettings(_env_file=None))
    with pytest.raises(BackendError, match="cannot serve"):
        await complete(backend, ModelRef(provider="hf_local", model="Qwen/VL"))


# --- streaming -----------------------------------------------------------------------------


def stream_lines(*words: str, tool_calls: list[dict[str, Any]] | None = None) -> list[dict]:
    lines: list[dict[str, Any]] = [
        {"model": "m", "message": {"role": "assistant", "content": w}, "done": False} for w in words
    ]
    final: dict[str, Any] = {
        "model": "m",
        "message": {
            "role": "assistant",
            "content": "",
            **({"tool_calls": tool_calls} if tool_calls else {}),
        },
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 21,
        "eval_count": 8,
    }
    return [*lines, final]


async def test_streaming_yields_deltas_then_a_final_chunk_with_usage(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (200, stream_lines("The ", "quick ", "fox"), 0)
    chunks = [
        c
        async for c in backend_for(ollama).stream(
            TXT,
            [{"role": "user", "content": "hi"}],
            temperature=0.0,
            max_tokens=None,
            timeout_s=5,
            tools=None,
        )
    ]
    assert ollama.requests[0][1]["stream"] is True
    assert "".join(c.delta for c in chunks) == "The quick fox"
    final = chunks[-1]
    assert final.finish_reason == "stop"
    assert (final.usage.prompt_tokens, final.usage.completion_tokens) == (21, 8)


async def test_streamed_tool_calls_are_assembled_on_the_final_chunk(ollama: FakeOllama) -> None:
    call = {"function": {"name": "count_objects", "arguments": {"camera": "cam02"}}}
    ollama.handler = lambda _p, _b: (200, stream_lines(tool_calls=[call]), 0)
    chunks = [
        c
        async for c in backend_for(ollama).stream(
            TXT, [{"role": "user", "content": "hi"}],
            temperature=0.0, max_tokens=None, timeout_s=5,
            tools=[{"type": "function", "function": {"name": "count_objects", "parameters": {}}}],
        )
    ]  # fmt: skip
    assert [(c.name, c.arguments) for c in chunks[-1].tool_calls] == [
        ("count_objects", {"camera": "cam02"})
    ]


async def test_a_stream_that_cannot_connect_raises_a_backend_error() -> None:
    backend = LiteLLMBackend(LLMSettings(_env_file=None, ollama_url="http://127.0.0.1:1"))
    with pytest.raises(BackendError) as caught:
        async for _ in backend.stream(
            TXT, [{"role": "user", "content": "hi"}],
            temperature=0.0, max_tokens=None, timeout_s=5, tools=None,
        ):  # fmt: skip
            pass
    assert caught.value.kind == "unavailable"


# --- unloading -----------------------------------------------------------------------------


async def test_unload_asks_ollama_to_keep_the_model_for_zero_seconds(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (200, {"done": True}, 0)
    await backend_for(ollama).unload("ollama:qwen2.5:3b")
    assert ollama.requests == [("/api/generate", {"model": "qwen2.5:3b", "keep_alive": 0})]


@pytest.mark.parametrize(
    "family", ["hf_local:Qwen/Qwen2.5-VL-3B-Instruct", "gemini:flash", "ollama:", ""]
)
async def test_unload_ignores_families_it_did_not_load(ollama: FakeOllama, family: str) -> None:
    await backend_for(ollama).unload(family)
    assert ollama.requests == []


async def test_a_failing_unload_is_not_an_error(ollama: FakeOllama) -> None:
    ollama.handler = lambda _p, _b: (500, {"error": "boom"}, 0)
    await backend_for(ollama).unload("ollama:qwen2.5:3b")  # must not raise
    dead = LiteLLMBackend(LLMSettings(_env_file=None, ollama_url="http://127.0.0.1:1"))
    await dead.unload("ollama:qwen2.5:3b")


# --- litellm bootstrap ---------------------------------------------------------------------


async def test_litellm_is_configured_not_to_phone_home_or_fetch_its_catalogue(
    ollama: FakeOllama,
) -> None:
    ollama.handler = lambda _p, _b: (200, chat_reply(), 0)
    backend = backend_for(ollama)
    await complete(backend)
    import litellm

    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"].lower() in {"true", "1"}
    assert litellm.telemetry is False
    assert litellm.drop_params is True


# --- the whole gateway over the real adapter -----------------------------------------------


class Verdict(BaseModel):
    verdict: str
    confidence: float


async def test_gateway_vision_call_end_to_end_over_litellm(ollama: FakeOllama) -> None:
    """Registry → gateway → lease → cache → LiteLLM → HTTP → validation, minus only the model."""
    import io

    from PIL import Image

    replies = iter(
        [
            chat_reply("sorry, here is my verdict: confirmed"),  # not JSON → repaired
            chat_reply('{"verdict": "confirmed", "confidence": 0.8}'),
        ]
    )
    ollama.handler = lambda _p, _b: (200, next(replies), 0)
    redis = FakeAsyncRedis(decode_responses=True)
    registry = ModelRegistry.from_file("config/models.yaml", profile="local")
    gateway = LLMGateway.from_settings(
        LLMSettings(_env_file=None, ollama_url=ollama.url, models_path="config/models.yaml"),
        redis=redis,
    )
    assert gateway.registry.task("event_verify").primary == registry.task("event_verify").primary

    frame = io.BytesIO()
    Image.new("RGB", (1280, 720), "grey").save(frame, format="JPEG")
    result = await gateway.vision(
        "event_verify", "Is a person inside the zone?", [ImageInput(data=frame.getvalue())],
        response_model=Verdict,
    )  # fmt: skip

    assert result.parsed == Verdict(verdict="confirmed", confidence=0.8)
    assert (result.attempts, result.provider, result.model) == (2, "ollama", "qwen2.5vl:3b")
    first, second = (body for _path, body in ollama.requests)
    assert first["options"]["num_ctx"] == 6144  # from config/models.yaml
    assert first["format"]["properties"]["verdict"]  # the response_model's schema went along
    assert len(first["messages"][0]["images"]) == 1
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]  # the repair

    again = await gateway.vision(
        "event_verify", "Is a person inside the zone?", [ImageInput(data=frame.getvalue())],
        response_model=Verdict,
    )  # fmt: skip
    assert again.cached and len(ollama.requests) == 2
    await redis.aclose()


# --- paths no HTTP round trip reaches ------------------------------------------------------


def test_tool_call_arguments_are_parsed_never_invented() -> None:
    from types import SimpleNamespace

    from vms_common.llm.backend import _tool_calls

    def item(arguments: Any, call_id: str | None = "x") -> SimpleNamespace:
        return SimpleNamespace(id=call_id, function=SimpleNamespace(name="f", arguments=arguments))

    calls = _tool_calls(
        [item('{"a": 1}'), item("  "), item("not json {"), item("[1, 2]"), item({"b": 2}, None)]
    )
    # Cloud providers send arguments as a JSON string; a small model's broken JSON is handed on
    # under a key the tool's own validation will reject, instead of being silently dropped.
    assert [c.arguments for c in calls] == [
        {"a": 1},
        {},
        {"_raw_arguments": "not json {"},
        {"_raw_arguments": [1, 2]},
        {"b": 2},
    ]
    assert [c.id for c in calls] == ["x", "x", "x", "x", "call_4"]
    assert _tool_calls(None) == []


@pytest.mark.parametrize(
    ("exception_name", "kind"),
    [
        ("Timeout", "timeout"),
        ("RateLimitError", "rate_limit"),
        ("AuthenticationError", "auth"),
        ("PermissionDeniedError", "auth"),
        ("NotFoundError", "not_found"),
        ("BadRequestError", "bad_request"),
        ("ContextWindowExceededError", "bad_request"),
        ("ContentPolicyViolationError", "bad_request"),
        ("UnprocessableEntityError", "bad_request"),
        ("APIConnectionError", "unavailable"),
        ("InternalServerError", "unavailable"),
        ("ServiceUnavailableError", "unavailable"),
        ("APIError", "unavailable"),
    ],
)
def test_provider_exceptions_are_classified(exception_name: str, kind: str) -> None:
    import httpx
    import litellm
    from vms_common.llm.backend import _translate

    exc_class = getattr(litellm, exception_name)
    response = httpx.Response(400, request=httpx.Request("POST", "http://provider.invalid"))
    needs_response = {"PermissionDeniedError", "UnprocessableEntityError"}
    if exception_name == "APIError":
        exc = exc_class(status_code=500, message="boom", llm_provider="groq", model="m")
    elif exception_name == "APIConnectionError":
        exc = exc_class(message="boom", llm_provider="groq", model="m", request=None)
    elif exception_name in needs_response:
        exc = exc_class(message="boom", model="m", llm_provider="groq", response=response)
    else:
        exc = exc_class(message="boom", model="m", llm_provider="groq")
    translated = _translate(litellm, exc)
    assert translated.kind == kind
    assert exception_name in str(translated)


def test_an_unknown_exception_is_unavailable_and_a_backend_error_passes_through() -> None:
    import litellm
    from vms_common.llm.backend import _translate

    assert _translate(litellm, RuntimeError("weird")).kind == "unavailable"
    original = BackendError("auth", "no key")
    assert _translate(litellm, original) is original
