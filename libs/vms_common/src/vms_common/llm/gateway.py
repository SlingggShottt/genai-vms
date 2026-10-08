"""LLMGateway — the one door every LLM/VLM call goes through (design_architecture.md §11.1).

A call names a *task*; the registry (`config/models.yaml`) turns it into an ordered list of
models for the active profile. For each model in turn the gateway:

    cache lookup → GPU lease (local models) → provider call → validate against response_model
    (re-asking with the validation errors when the reply is malformed) → cache store

and moves on to the next model when one fails, so a hosted model's outage, rate limit or
missing key degrades to its fallback instead of failing the caller.

What the caller sees when everything failed (style_guide.md §A.5 status mapping):
`LLMUnavailableError` (→ 503), `LLMOutputError` (→ 422); the exception type follows the
task's *primary* model, since that is the one whose failure needs fixing.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar, overload

from pydantic import BaseModel
from redis.asyncio import Redis

from vms_common.config import LLMSettings, RedisSettings
from vms_common.llm import metrics
from vms_common.llm.backend import Backend, BackendError, LiteLLMBackend, RawCompletion
from vms_common.llm.cache import ResponseCache, cache_key
from vms_common.llm.errors import (
    GPULeaseTimeoutError,
    LLMError,
    LLMOutputError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from vms_common.llm.images import prepare_images, to_data_url
from vms_common.llm.lease import GPULease
from vms_common.llm.registry import ModelRef, ModelRegistry, TaskConfig
from vms_common.llm.structured import (
    describe_error,
    parse_structured,
    repair_messages,
    response_format_for,
)
from vms_common.llm.types import (
    ChatChunk,
    ChatResult,
    ImageInput,
    Message,
    ToolSpec,
    Usage,
)
from vms_common.logging import get_logger
from vms_common.redis import get_redis_client

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# litellm enforces `timeout_s` itself; this outer deadline only catches a provider that
# ignores it, so it must not fire first.
_TIMEOUT_SLACK_S = 5.0


class Gateway(Protocol):
    """What callers depend on. `LLMGateway` and `testing.FakeGateway` both satisfy it, so a
    service takes a `Gateway` and its tests hand it a `FakeGateway`."""

    async def chat(
        self,
        task: str,
        messages: Sequence[Message | Mapping[str, Any]],
        *,
        response_model: type[BaseModel] | None = None,
        tools: Sequence[ToolSpec] | None = None,
        stream: bool = False,
    ) -> ChatResult | AsyncIterator[ChatChunk]: ...

    async def vision(
        self,
        task: str,
        prompt: str,
        images: Sequence[ImageInput],
        *,
        response_model: type[BaseModel] | None = None,
        system: str | None = None,
    ) -> ChatResult: ...


@dataclass
class _Stats:
    """Model calls spent so far on one gateway call (validation retries + fallbacks)."""

    calls: int = 0


class LLMGateway:
    def __init__(
        self,
        registry: ModelRegistry,
        backends: Mapping[str, Backend],
        *,
        lease: GPULease | None = None,
        cache: ResponseCache | None = None,
        lease_wait_s: float = 120.0,
        redis_to_close: Redis | None = None,
    ) -> None:
        self._registry = registry
        self._backends: dict[str, Backend] = dict(backends)
        self._lease = lease
        self._cache = cache
        self._lease_wait_s = lease_wait_s
        self._redis_to_close = redis_to_close
        self._warned_no_lease = False

    @classmethod
    def from_settings(
        cls,
        settings: LLMSettings | None = None,
        *,
        redis: Redis | None = None,
        redis_settings: RedisSettings | None = None,
    ) -> LLMGateway:
        """The production wiring: registry from `VMS_LLM_MODELS_PATH` for `VMS_LLM_PROFILE`,
        LiteLLM for the four hosted/Ollama providers, lease + cache on Redis."""
        settings = settings or LLMSettings()
        registry = ModelRegistry.from_file(settings.models_path, profile=settings.profile)
        client = redis or get_redis_client(redis_settings)
        backend = LiteLLMBackend(settings)
        backends: dict[str, Backend] = dict.fromkeys(LiteLLMBackend.PROVIDERS, backend)
        if registry.uses_provider("hf_local"):  # only then: it pulls in torch on first use
            from vms_common.llm.hf_local import HfLocalBackend  # noqa: PLC0415

            backends["hf_local"] = HfLocalBackend(settings)
        return cls(
            registry,
            backends,
            lease=GPULease(client, node=settings.lease_node, ttl_s=settings.lease_ttl_seconds),
            cache=ResponseCache(client),
            lease_wait_s=settings.lease_wait_seconds,
            redis_to_close=None if redis is not None else client,
        )

    async def aclose(self) -> None:
        if self._redis_to_close is not None:
            await self._redis_to_close.aclose()

    def register_backend(self, provider: str, backend: Backend) -> None:
        """Plug in a provider this gateway was not built with (hf_local, story P5-D5)."""
        self._backends[provider] = backend

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    @property
    def profile(self) -> str:
        return self._registry.profile

    # --- public interface --------------------------------------------------------------

    @overload
    async def chat(
        self,
        task: str,
        messages: Sequence[Message | Mapping[str, Any]],
        *,
        response_model: type[BaseModel] | None = None,
        tools: Sequence[ToolSpec] | None = None,
        stream: Literal[False] = False,
    ) -> ChatResult: ...

    @overload
    async def chat(
        self,
        task: str,
        messages: Sequence[Message | Mapping[str, Any]],
        *,
        response_model: None = None,
        tools: Sequence[ToolSpec] | None = None,
        stream: Literal[True],
    ) -> AsyncIterator[ChatChunk]: ...

    async def chat(
        self,
        task: str,
        messages: Sequence[Message | Mapping[str, Any]],
        *,
        response_model: type[BaseModel] | None = None,
        tools: Sequence[ToolSpec] | None = None,
        stream: bool = False,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        """Chat with the model serving `task`.

        With `response_model` the reply is validated (and re-asked on failure) and returned in
        `result.parsed`. With `stream=True` an async iterator of `ChatChunk` comes back — use
        `async for chunk in await gateway.chat(..., stream=True)`; the final chunk carries the
        tool calls and usage. Streams are not cached and cannot be combined with
        `response_model`.
        """
        cfg = self._registry.task(task)
        turns = [m if isinstance(m, Message) else Message.model_validate(m) for m in messages]
        if not turns:
            raise LLMRequestError("messages must not be empty")
        if response_model is not None and tools:
            raise LLMRequestError("response_model and tools cannot be combined in one call")
        if stream:
            if response_model is not None:
                raise LLMRequestError("stream=True cannot be combined with response_model")
            return self._stream(cfg, turns, tools)
        return await self._run(cfg, turns, response_model, tools, [])

    async def vision(
        self,
        task: str,
        prompt: str,
        images: Sequence[ImageInput],
        *,
        response_model: type[BaseModel] | None = None,
        system: str | None = None,
    ) -> ChatResult:
        """Ask a vision task about `images`. The task's `max_images` / `max_image_edge` are
        enforced here: too many images is a `LLMRequestError`, oversized ones are shrunk."""
        cfg = self._registry.task(task)
        if cfg.modality != "vision":
            raise LLMRequestError(f"task {task!r} is text-only; use chat()")
        prepared = await asyncio.to_thread(
            prepare_images, images, max_images=cfg.max_images, max_edge=cfg.max_image_edge
        )
        turns = [Message(role="system", content=system)] if system else []
        turns.append(Message(role="user", content=prompt))
        return await self._run(cfg, turns, response_model, None, prepared)

    # --- one call: walk the candidates -------------------------------------------------

    async def _run(
        self,
        cfg: TaskConfig,
        turns: list[Message],
        response_model: type[BaseModel] | None,
        tools: Sequence[ToolSpec] | None,
        images: list[ImageInput],
    ) -> ChatResult:
        started = time.monotonic()
        stats = _Stats()
        failures: list[str] = []
        first_error: LLMError | None = None
        candidates = cfg.candidates
        for index, ref in enumerate(candidates):
            try:
                result = await self._attempt(cfg, ref, turns, response_model, tools, images, stats)
            except (LLMUnavailableError, LLMOutputError) as exc:
                first_error = first_error or exc
                failures.append(f"{ref.label()}: {exc}")
                more = index + 1 < len(candidates)
                log.warning(
                    "llm_candidate_failed",
                    task=cfg.task,
                    provider=ref.provider,
                    model=ref.model,
                    error=type(exc).__name__,
                    trying_fallback=more,
                )
                if more:
                    metrics.fallbacks_total.labels(cfg.task).inc()
                continue
            result.fallback_index = index
            result.attempts = stats.calls
            result.latency_s = time.monotonic() - started
            return result
        raise _exhausted(cfg, first_error, failures)

    async def _attempt(
        self,
        cfg: TaskConfig,
        ref: ModelRef,
        turns: list[Message],
        response_model: type[BaseModel] | None,
        tools: Sequence[ToolSpec] | None,
        images: list[ImageInput],
        stats: _Stats,
    ) -> ChatResult:
        backend = self._backends.get(ref.provider)
        if backend is None:
            raise LLMUnavailableError(f"no backend registered for provider {ref.provider!r}")
        wire = _wire_messages(turns, images)
        schema = response_model.model_json_schema() if response_model else None

        key: str | None = None
        if self._cache is not None and cfg.cache_ttl_s > 0 and not tools:
            key = cache_key(
                task=cfg.task,
                ref=ref,
                messages=wire,
                response_schema=schema,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            hit = await self._cache.get(key)
            cached = _from_cache(cfg, ref, hit, response_model) if hit is not None else None
            metrics.cache_total.labels(cfg.task, "hit" if cached else "miss").inc()
            if cached is not None:
                return cached

        async with self._gpu(ref):
            result = await self._call(
                cfg, ref, backend, wire, response_model, _wire_tools(tools), stats
            )

        if key is not None and self._cache is not None:
            await self._cache.set(key, _to_cache(result), ttl_s=cfg.cache_ttl_s)
        return result

    async def _call(
        self,
        cfg: TaskConfig,
        ref: ModelRef,
        backend: Backend,
        wire: list[dict[str, Any]],
        response_model: type[BaseModel] | None,
        wire_tools: list[dict[str, Any]] | None,
        stats: _Stats,
    ) -> ChatResult:
        """Call the model; if a reply fails validation, show the model its mistake and ask
        again, up to `validation_retries` more times."""
        working = list(wire)
        response_format = response_format_for(response_model) if response_model else None
        tries = 1 + (cfg.validation_retries if response_model else 0)
        last_text = ""
        rejections: list[str] = []
        for attempt in range(tries):
            raw = await self._timed(cfg, ref, backend, working, response_format, wire_tools, stats)
            result = ChatResult(
                task=cfg.task,
                provider=ref.provider,
                model=ref.model,
                text=raw.text,
                tool_calls=raw.tool_calls,
                usage=raw.usage,
                finish_reason=raw.finish_reason,
            )
            if response_model is None:
                return result
            try:
                result.parsed = parse_structured(raw.text, response_model)
            except ValueError as exc:
                last_text = raw.text
                reason = describe_error(exc)
                rejections.append(reason)
                log.info(
                    "llm_reply_rejected",
                    task=cfg.task,
                    provider=ref.provider,
                    model=ref.model,
                    attempt=attempt + 1,
                    reason=reason,
                )
                if attempt + 1 < tries:
                    metrics.retries_total.labels(cfg.task).inc()
                    working = [*working, *repair_messages(raw.text, reason)]
                continue
            return result
        raise LLMOutputError(
            f"{ref.label()} gave {tries} replies that do not match "
            f"{response_model.__name__}: {rejections[-1]}",
            last_text=last_text,
            failures=rejections,
        )

    async def _timed(
        self,
        cfg: TaskConfig,
        ref: ModelRef,
        backend: Backend,
        wire: list[dict[str, Any]],
        response_format: dict[str, Any] | None,
        wire_tools: list[dict[str, Any]] | None,
        stats: _Stats,
    ) -> RawCompletion:
        timeout_s = cfg.timeout_for(ref)
        stats.calls += 1
        status = "ok"
        started = time.monotonic()
        try:
            async with asyncio.timeout(timeout_s + _TIMEOUT_SLACK_S):
                raw = await backend.complete(
                    ref,
                    wire,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                    timeout_s=timeout_s,
                    response_format=response_format,
                    tools=wire_tools,
                )
        except TimeoutError as exc:
            status = "timeout"
            raise LLMTimeoutError(f"{ref.label()} did not answer within {timeout_s:.0f}s") from exc
        except BackendError as exc:
            status = exc.kind
            raise _to_unavailable(ref, exc) from exc
        finally:
            metrics.request_seconds.labels(ref.provider, cfg.task, status).observe(
                time.monotonic() - started
            )
        _count_tokens(ref, cfg.task, raw.usage)
        return raw

    # --- GPU lease ---------------------------------------------------------------------

    @asynccontextmanager
    async def _gpu(self, ref: ModelRef) -> AsyncIterator[None]:
        """Hold the GPU lease while a local model runs; unload what it displaces."""
        if not ref.needs_gpu:
            yield
            return
        if self._lease is None:
            if not self._warned_no_lease:
                self._warned_no_lease = True
                log.warning("gpu_lease_disabled", reason="gateway built without a lease")
            yield
            return
        async with self._lease.hold(ref.family, wait_s=self._lease_wait_s) as grant:
            if grant.previous_family:
                await self._unload(grant.previous_family)
            yield

    async def _unload(self, family: str) -> None:
        backend = self._backends.get(family.partition(":")[0])
        if backend is None:
            return
        try:
            await backend.unload(family)
        except Exception as exc:  # best effort: the next model load evicts it anyway
            log.warning("model_unload_failed", family=family, error=type(exc).__name__)

    # --- streaming ---------------------------------------------------------------------

    async def _stream(
        self,
        cfg: TaskConfig,
        turns: list[Message],
        tools: Sequence[ToolSpec] | None,
    ) -> AsyncIterator[ChatChunk]:
        wire = _wire_messages(turns, [])
        wire_tools = _wire_tools(tools)
        failures: list[str] = []
        first_error: LLMError | None = None
        candidates = cfg.candidates
        for index, ref in enumerate(candidates):
            timeout_s = cfg.timeout_for(ref)
            started = time.monotonic()
            started_output = False
            status = "ok"
            usage = Usage()
            try:
                backend = self._backends.get(ref.provider)
                if backend is None:
                    raise LLMUnavailableError(
                        f"no backend registered for provider {ref.provider!r}"
                    )
                async with self._gpu(ref):
                    pieces = backend.stream(
                        ref,
                        wire,
                        temperature=cfg.temperature,
                        max_tokens=cfg.max_tokens,
                        timeout_s=timeout_s,
                        tools=wire_tools,
                    ).__aiter__()
                    try:
                        while True:
                            try:
                                # An idle limit per chunk: a long answer may take long overall.
                                async with asyncio.timeout(timeout_s + _TIMEOUT_SLACK_S):
                                    chunk = await anext(pieces)
                            except StopAsyncIteration:
                                break
                            started_output = True
                            if chunk.usage is not None:
                                usage = chunk.usage
                            yield chunk
                    finally:
                        await _aclose(pieces)
            except (TimeoutError, BackendError, LLMUnavailableError) as raised:
                status = _status_of(raised)
                error = _as_unavailable(ref, raised, timeout_s)
                if started_output:
                    # Part of the answer is already with the caller: switching models now would
                    # splice two different answers together.
                    raise error from raised
                first_error = first_error or error
                failures.append(f"{ref.label()}: {error}")
                more = index + 1 < len(candidates)
                log.warning(
                    "llm_candidate_failed",
                    task=cfg.task,
                    provider=ref.provider,
                    model=ref.model,
                    error=type(error).__name__,
                    trying_fallback=more,
                )
                if more:
                    metrics.fallbacks_total.labels(cfg.task).inc()
                continue
            finally:
                metrics.request_seconds.labels(ref.provider, cfg.task, status).observe(
                    time.monotonic() - started
                )
            _count_tokens(ref, cfg.task, usage)
            return
        raise _exhausted(cfg, first_error, failures)


# --- helpers ---------------------------------------------------------------------------


def _wire_messages(turns: Sequence[Message], images: Sequence[ImageInput]) -> list[dict[str, Any]]:
    """Messages in the OpenAI chat shape every LiteLLM provider accepts. Images ride on the
    last user turn as `image_url` parts (data URLs, so nothing is fetched by the provider)."""
    wire: list[dict[str, Any]] = []
    for turn in turns:
        entry: dict[str, Any] = {"role": turn.role, "content": turn.content}
        if turn.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in turn.tool_calls
            ]
        if turn.tool_call_id is not None:
            entry["tool_call_id"] = turn.tool_call_id
        if turn.name is not None:
            entry["name"] = turn.name
        wire.append(entry)
    if images:
        target = next((m for m in reversed(wire) if m["role"] == "user"), None)
        if target is None:
            raise LLMRequestError("images need a user message to attach to")
        target["content"] = [
            {"type": "text", "text": target["content"] or ""},
            *({"type": "image_url", "image_url": {"url": to_data_url(i)}} for i in images),
        ]
    return wire


def _wire_tools(tools: Sequence[ToolSpec] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


def _to_unavailable(ref: ModelRef, exc: BackendError) -> LLMUnavailableError:
    message = f"{ref.label()} [{exc.kind}]: {exc}"
    if exc.kind == "timeout":
        return LLMTimeoutError(message)
    return LLMUnavailableError(message)


def _count_tokens(ref: ModelRef, task: str, usage: Usage) -> None:
    if usage.prompt_tokens:
        metrics.tokens_total.labels(ref.provider, task, "prompt").inc(usage.prompt_tokens)
    if usage.completion_tokens:
        metrics.tokens_total.labels(ref.provider, task, "completion").inc(usage.completion_tokens)


def _as_unavailable(
    ref: ModelRef, exc: TimeoutError | BackendError | LLMUnavailableError, timeout_s: float
) -> LLMUnavailableError:
    if isinstance(exc, TimeoutError):
        return LLMTimeoutError(f"{ref.label()} sent nothing for {timeout_s:.0f}s")
    if isinstance(exc, BackendError):
        return _to_unavailable(ref, exc)
    return exc


def _status_of(exc: TimeoutError | BackendError | LLMUnavailableError) -> str:
    """The `status` label of vms_llm_request_seconds for a failed call."""
    if isinstance(exc, TimeoutError | LLMTimeoutError):
        return "timeout"
    if isinstance(exc, BackendError):
        return exc.kind
    return "unavailable"


async def _aclose(iterator: Any) -> None:
    aclose = getattr(iterator, "aclose", None)
    if aclose is not None:
        await aclose()


def _exhausted(cfg: TaskConfig, first_error: LLMError | None, failures: list[str]) -> LLMError:
    message = f"every model for task {cfg.task!r} failed — " + " | ".join(failures)
    if first_error is None:  # unreachable while a task has at least its primary model
        return LLMUnavailableError(f"task {cfg.task!r} has no models to try")
    if isinstance(first_error, LLMOutputError):
        return LLMOutputError(message, last_text=first_error.last_text, failures=failures)
    if isinstance(first_error, GPULeaseTimeoutError):
        return GPULeaseTimeoutError(message, failures=failures)
    if isinstance(first_error, LLMTimeoutError):
        return LLMTimeoutError(message, failures=failures)
    return LLMUnavailableError(message, failures=failures)


def _to_cache(result: ChatResult) -> dict[str, Any]:
    return {
        "text": result.text,
        "usage": result.usage.model_dump(),
        "finish_reason": result.finish_reason,
    }


def _from_cache(
    cfg: TaskConfig,
    ref: ModelRef,
    entry: dict[str, Any],
    response_model: type[BaseModel] | None,
) -> ChatResult | None:
    """Rebuild a result from a cache entry, or None if it no longer fits (it is re-validated:
    a response_model edited since the entry was written must not be served stale)."""
    try:
        text = entry["text"]
        result = ChatResult(
            task=cfg.task,
            provider=ref.provider,
            model=ref.model,
            text=text,
            usage=Usage.model_validate(entry.get("usage") or {}),
            finish_reason=entry.get("finish_reason"),
            cached=True,
            attempts=0,
        )
        if response_model is not None:
            result.parsed = parse_structured(text, response_model)
    except (KeyError, TypeError, ValueError):
        return None
    return result
