"""Provider backends: what actually talks to a model.

`Backend` is the seam between the gateway's policy (registry, fallbacks, validation retries,
lease, cache) and a provider's wire protocol. `LiteLLMBackend` serves ollama, gemini, groq and
openrouter; `hf_local` (fine-tuned adapters via transformers + PEFT, story P5-D5) plugs in
later through `LLMGateway.register_backend` without touching the gateway. Tests substitute a
fake `Backend`, so no unit test needs the network or litellm.

This is the only module that imports litellm, and only on first use.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from vms_common.config import LLMSettings
from vms_common.llm.registry import ModelRef
from vms_common.llm.types import ChatChunk, ToolCall, Usage
from vms_common.logging import get_logger

log = get_logger(__name__)

ErrorKind = Literal["timeout", "rate_limit", "auth", "not_found", "bad_request", "unavailable"]


class BackendError(Exception):
    """A provider call failed. `kind` feeds metrics and logs; the gateway handles every kind
    the same way (try the next candidate), because "Gemini rejected our key" is exactly the
    case a Groq fallback exists for."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class RawCompletion:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None


class Backend(Protocol):
    """What a provider must offer the gateway.

    Every failure of a call — network, quota, bad key, unknown model, timeout — must surface
    as `BackendError`. Anything else is treated as a bug in the backend and propagates past the
    fallback chain, so a custom backend (hf_local) has to translate its own exceptions.
    """

    async def complete(
        self,
        ref: ModelRef,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None,
        timeout_s: float,
        response_format: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
    ) -> RawCompletion: ...

    def stream(
        self,
        ref: ModelRef,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None,
        timeout_s: float,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[ChatChunk]: ...

    async def unload(self, family: str) -> None:
        """Free the GPU memory of a model family this backend loaded. Best effort."""
        ...


class LiteLLMBackend:
    """ollama / gemini / groq / openrouter through LiteLLM."""

    PROVIDERS = ("ollama", "gemini", "groq", "openrouter")

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self._settings = settings or LLMSettings()
        self._litellm: Any = None
        self._known_ollama_models: set[str] = set()

    # --- litellm bootstrap -------------------------------------------------------------

    def _lib(self) -> Any:
        if self._litellm is None:
            # litellm downloads its model-price catalogue from GitHub when imported (3 retries,
            # several seconds, then a warning) — on an offline demo laptop that is pure delay.
            # The copy bundled in the wheel is all we use it for. This must be set before the
            # import, which is why it is an environment write and not a setting.
            os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
            import litellm  # noqa: PLC0415  (deferred: heavy, and only gateway users need it)

            litellm.telemetry = False
            # Drop request parameters a provider does not support (e.g. `response_format` on a
            # Groq Llama) instead of failing: the validate-and-retry loop guards the output.
            litellm.drop_params = True
            self._litellm = litellm
        return self._litellm

    def _declare_ollama_model(self, model: str) -> None:
        """Tell litellm this Ollama model exists, at no cost, so it never looks it up itself.

        For a model missing from its price catalogue litellm asks the Ollama server about it
        (`POST /api/show`) while working out the call's cost — with a *synchronous* HTTP client,
        on the event loop, and at litellm's *default* `localhost:11434`, not the host we
        configured. We neither need litellm's cost figures nor can afford a blocking call.

        The entry is added to `litellm.model_cost` directly: the documented `register_model()`
        itself runs that very lookup for a model it has not seen yet.
        """
        if model in self._known_ollama_models:
            return
        self._lib().model_cost[f"ollama_chat/{model}"] = {
            "litellm_provider": "ollama_chat",
            "mode": "chat",
            "input_cost_per_token": 0.0,
            "output_cost_per_token": 0.0,
        }
        self._known_ollama_models.add(model)

    def _call_kwargs(self, ref: ModelRef, timeout_s: float) -> dict[str, Any]:
        s = self._settings
        kwargs: dict[str, Any] = {"model": ref.litellm_model, "timeout": timeout_s}
        if ref.provider == "ollama":
            self._declare_ollama_model(ref.model)
            kwargs["api_base"] = s.effective_ollama_url
            if ref.keep_alive is not None:
                kwargs["keep_alive"] = ref.keep_alive
            if ref.num_ctx is not None:
                kwargs["num_ctx"] = ref.num_ctx
            return kwargs
        keys = {
            "gemini": s.gemini_api_key,
            "groq": s.groq_api_key,
            "openrouter": s.openrouter_api_key,
        }
        if ref.provider not in keys:
            raise BackendError("unavailable", f"LiteLLMBackend cannot serve {ref.provider!r}")
        key = keys[ref.provider].get_secret_value()
        if not key:
            env_name = f"{ref.provider.upper()}_API_KEY"
            raise BackendError("auth", f"{env_name} is not set")
        kwargs["api_key"] = key
        return kwargs

    # --- Backend protocol --------------------------------------------------------------

    async def complete(
        self,
        ref: ModelRef,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None,
        timeout_s: float,
        response_format: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
    ) -> RawCompletion:
        litellm = self._lib()
        kwargs = self._call_kwargs(ref, timeout_s)
        try:
            response = await litellm.acompletion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                tools=tools,
                **kwargs,
            )
        except Exception as exc:
            raise _translate(litellm, exc) from exc
        choice = response.choices[0]
        message = choice.message
        usage = getattr(response, "usage", None)
        return RawCompletion(
            text=message.content or "",
            tool_calls=_tool_calls(getattr(message, "tool_calls", None)),
            usage=Usage(
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            ),
            finish_reason=choice.finish_reason,
        )

    async def stream(
        self,
        ref: ModelRef,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None,
        timeout_s: float,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[ChatChunk]:
        litellm = self._lib()
        kwargs = self._call_kwargs(ref, timeout_s)
        pieces: list[Any] = []
        try:
            response = await litellm.acompletion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                stream=True,
                stream_options={"include_usage": True},
                **kwargs,
            )
            async for piece in response:
                pieces.append(piece)
                delta = piece.choices[0].delta if piece.choices else None
                if delta is not None and delta.content:
                    yield ChatChunk(delta=delta.content)
        except Exception as exc:
            raise _translate(litellm, exc) from exc
        # Tool-call arguments arrive in fragments across chunks; litellm knows how to stitch a
        # finished response (tool calls, usage, finish reason) back together.
        rebuilt = litellm.stream_chunk_builder(pieces, messages=messages) if pieces else None
        if rebuilt is None:
            yield ChatChunk(finish_reason="stop")
            return
        choice = rebuilt.choices[0]
        usage = getattr(rebuilt, "usage", None)
        yield ChatChunk(
            tool_calls=_tool_calls(getattr(choice.message, "tool_calls", None)),
            finish_reason=choice.finish_reason,
            usage=Usage(
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            ),
        )

    async def unload(self, family: str) -> None:
        provider, _, model = family.partition(":")
        if provider != "ollama" or not model:
            return
        # Ollama frees a model when asked to keep it for zero seconds.
        url = f"{self._settings.effective_ollama_url.rstrip('/')}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json={"model": model, "keep_alive": 0})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Ollama evicts on its own when the next model needs the room; this is a courtesy.
            log.warning("ollama_unload_failed", model=model, error=type(exc).__name__)
            return
        log.info("ollama_model_unloaded", model=model)


def _tool_calls(raw: list[Any] | None) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for index, item in enumerate(raw or []):
        function = item.function
        arguments: Any = function.arguments
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except ValueError:
                # Small models do emit broken JSON here. Hand the raw text on under a key the
                # tool's own argument validation will reject, rather than inventing arguments.
                arguments = {"_raw_arguments": arguments}
        if not isinstance(arguments, dict):
            arguments = {"_raw_arguments": arguments}
        calls.append(
            ToolCall(id=item.id or f"call_{index}", name=function.name, arguments=arguments)
        )
    return calls


def _translate(litellm: Any, exc: Exception) -> BackendError:
    """Map a litellm/provider exception onto `BackendError`. Order matters: several of these
    are subclasses of each other (Timeout is an APIConnectionError)."""
    if isinstance(exc, BackendError):
        return exc
    kind: ErrorKind
    if isinstance(exc, litellm.Timeout):
        kind = "timeout"
    elif isinstance(exc, litellm.RateLimitError):
        kind = "rate_limit"
    elif isinstance(exc, litellm.AuthenticationError | litellm.PermissionDeniedError):
        kind = "auth"
    elif isinstance(exc, litellm.NotFoundError):
        kind = "not_found"
    elif isinstance(
        exc,
        litellm.BadRequestError
        | litellm.ContextWindowExceededError
        | litellm.ContentPolicyViolationError
        | litellm.UnprocessableEntityError,
    ):
        kind = "bad_request"
    else:
        kind = "unavailable"
    # Provider messages can be long and (rarely) echo request fragments: keep them short.
    return BackendError(kind, f"{type(exc).__name__}: {str(exc)[:300]}")
