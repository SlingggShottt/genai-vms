"""FakeGateway — a drop-in `Gateway` for tests (CLAUDE.md: tests never hit the network or a
real LLM). Script what each task should answer; the fake records every call so a test can
assert on the prompt, the images and the requested `response_model`.

    gateway = FakeGateway({
        "event_verify": [{"verdict": "confirmed", "confidence": 0.9, "reason": "..."}],
        "query_decompose": QueryPlan(...),                   # bare value: answers every call
        "rerank": [LLMUnavailableError("gemini is down")],   # exceptions are raised
    })
    result = await gateway.vision("event_verify", "prompt", [image], response_model=Verdict)
    assert result.parsed.verdict == "confirmed"
    assert gateway.calls_for("event_verify")[0].images

Scripted values: `str` (the raw reply), `dict`/`list` (JSON reply), a `BaseModel` (its JSON),
a `ChatResult` (returned as is), an exception instance (raised), a callable taking the
`RecordedCall` (returns any of these). A *list or tuple* is a queue consumed one call at a
time — running past its end raises `UnscriptedCallError`, so a test that makes an unexpected
extra call fails loudly instead of getting a stale answer. Anything else repeats forever.

Replies go through the same extraction and validation the real gateway uses, so a recording
that would not validate in production does not validate here either.

Recordings live in JSON files: `FakeGateway.from_recording(path)` reads
`{"<task>": <value or list of values>}`; a failure is written
`{"$error": "unavailable" | "timeout" | "output", "message": "..."}`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from vms_common.llm.backend import RawCompletion
from vms_common.llm.errors import (
    LLMOutputError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from vms_common.llm.registry import ModelRef, ModelRegistry
from vms_common.llm.structured import parse_structured
from vms_common.llm.types import (
    ChatChunk,
    ChatResult,
    ImageInput,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)

_ERRORS: dict[str, type[Exception]] = {
    "unavailable": LLMUnavailableError,
    "timeout": LLMTimeoutError,
    "output": LLMOutputError,
}


class UnscriptedCallError(AssertionError):
    """The code under test called a task the fake had no (more) answer for."""


@dataclass
class RecordedCall:
    method: Literal["chat", "vision"]
    task: str
    messages: list[Message]
    images: list[ImageInput] = field(default_factory=list)
    response_model: type[BaseModel] | None = None
    tools: list[ToolSpec] | None = None
    stream: bool = False

    @property
    def prompt(self) -> str:
        """Text of the last user message — usually the prompt under test."""
        for message in reversed(self.messages):
            if message.role == "user":
                return message.content or ""
        return ""


class FakeGateway:
    def __init__(
        self,
        responses: Mapping[str, Any] | None = None,
        *,
        registry: ModelRegistry | None = None,
    ) -> None:
        """`registry` is optional; with one, unknown tasks, `vision()` on a text task and too
        many images fail as they would for real."""
        self._script: dict[str, Any] = {}
        self._queues: dict[str, list[Any]] = {}
        self._registry = registry
        self.calls: list[RecordedCall] = []
        for task, value in (responses or {}).items():
            self.script(task, value)

    # --- scripting ---------------------------------------------------------------------

    def script(self, task: str, value: Any) -> FakeGateway:
        """Set the answer(s) for `task`, replacing any earlier script for it."""
        self._script.pop(task, None)
        self._queues.pop(task, None)
        if isinstance(value, list | tuple):
            self._queues[task] = list(value)
        else:
            self._script[task] = value
        return self

    @classmethod
    def from_recording(
        cls, path: str | Path, *, registry: ModelRegistry | None = None
    ) -> FakeGateway:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"recording {path} must be a JSON object of task → answer(s)")
        return cls(
            {
                task: [_from_json(v) for v in value]
                if isinstance(value, list)
                else _from_json(value)
                for task, value in raw.items()
            },
            registry=registry,
        )

    def calls_for(self, task: str) -> list[RecordedCall]:
        return [c for c in self.calls if c.task == task]

    def unused(self) -> dict[str, int]:
        """Queued answers nobody asked for — for `assert not gateway.unused()` at test end."""
        return {task: len(queue) for task, queue in self._queues.items() if queue}

    # --- Gateway interface -------------------------------------------------------------

    async def chat(
        self,
        task: str,
        messages: Sequence[Message | Mapping[str, Any]],
        *,
        response_model: type[BaseModel] | None = None,
        tools: Sequence[ToolSpec] | None = None,
        stream: bool = False,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        turns = [m if isinstance(m, Message) else Message.model_validate(m) for m in messages]
        if not turns:
            raise LLMRequestError("messages must not be empty")
        if stream and response_model is not None:
            raise LLMRequestError("stream=True cannot be combined with response_model")
        if response_model is not None and tools:
            raise LLMRequestError("response_model and tools cannot be combined in one call")
        if self._registry is not None:
            self._registry.task(task)
        call = RecordedCall(
            "chat", task, turns, response_model=response_model,
            tools=list(tools) if tools else None, stream=stream,
        )  # fmt: skip
        result = self._answer(call)
        return _chunks(result) if stream else result

    async def vision(
        self,
        task: str,
        prompt: str,
        images: Sequence[ImageInput],
        *,
        response_model: type[BaseModel] | None = None,
        system: str | None = None,
    ) -> ChatResult:
        if not images:
            raise LLMRequestError("vision() needs at least one image")
        if self._registry is not None:
            cfg = self._registry.task(task)
            if cfg.modality != "vision":
                raise LLMRequestError(f"task {task!r} is text-only; use chat()")
            if len(images) > cfg.max_images:
                raise LLMRequestError(
                    f"{len(images)} images exceed this task's cap of {cfg.max_images}"
                )
        turns = [Message(role="system", content=system)] if system else []
        turns.append(Message(role="user", content=prompt))
        call = RecordedCall(
            "vision", task, turns, images=list(images), response_model=response_model
        )
        return self._answer(call)

    # --- internals ---------------------------------------------------------------------

    def _answer(self, call: RecordedCall) -> ChatResult:
        self.calls.append(call)
        value = self._next(call.task)
        if callable(value):
            value = value(call)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, ChatResult):
            return value
        if isinstance(value, ToolCall):
            value = [value]
        if isinstance(value, list) and value and all(isinstance(v, ToolCall) for v in value):
            return _result(call, text="", tool_calls=value)

        text = _as_text(value)
        result = _result(call, text=text)
        if call.response_model is not None:
            try:
                result.parsed = parse_structured(text, call.response_model)
            except ValueError as exc:
                raise LLMOutputError(
                    f"scripted reply for {call.task!r} does not match "
                    f"{call.response_model.__name__}: {exc}",
                    last_text=text,
                ) from exc
        return result

    def _next(self, task: str) -> Any:
        if task in self._queues:
            queue = self._queues[task]
            if not queue:
                raise UnscriptedCallError(
                    f"FakeGateway: every scripted answer for {task!r} is used up"
                )
            return queue.pop(0)
        if task in self._script:
            return self._script[task]
        raise UnscriptedCallError(f"FakeGateway: no answer scripted for task {task!r}")


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value)


def _result(
    call: RecordedCall, *, text: str, tool_calls: list[ToolCall] | None = None
) -> ChatResult:
    return ChatResult(
        task=call.task,
        provider="fake",
        model="fake",
        text=text,
        tool_calls=tool_calls or [],
        finish_reason="tool_calls" if tool_calls else "stop",
    )


async def _chunks(result: ChatResult) -> AsyncIterator[ChatChunk]:
    words = result.text.split(" ")
    for index, word in enumerate(words):
        yield ChatChunk(delta=word if index == len(words) - 1 else word + " ")
    yield ChatChunk(
        tool_calls=result.tool_calls, finish_reason=result.finish_reason, usage=result.usage
    )


def _from_json(value: Any) -> Any:
    if isinstance(value, dict) and "$error" in value:
        kind = value["$error"]
        if kind not in _ERRORS:
            raise ValueError(f"unknown recorded $error {kind!r}; expected one of {sorted(_ERRORS)}")
        return _ERRORS[kind](value.get("message", f"recorded {kind} error"))
    return value


# --- ScriptedBackend: a fake provider, to test the real LLMGateway -----------------------


@dataclass
class BackendCall:
    """What the gateway sent to the provider for one model call."""

    ref: ModelRef
    messages: list[dict[str, Any]]
    temperature: float
    max_tokens: int | None
    timeout_s: float
    response_format: dict[str, Any] | None
    tools: list[dict[str, Any]] | None
    streamed: bool = False


class ScriptedBackend:
    """A `Backend` that answers from a script, for tests of `LLMGateway` itself (policy:
    fallbacks, retries, lease, cache). Services under test should use `FakeGateway` instead.

    Replies are consumed in order, one per model call (streamed or not): a `str` (reply text),
    a `RawCompletion`, an exception (raised), or a callable taking the `BackendCall` that
    returns any of these (it may be `async`, and may inspect state mid-call). For a streamed
    call a reply may also be a list of `ChatChunk`/`str`/exceptions, where a number means
    "pause that many seconds" (to simulate a stalled stream).
    """

    def __init__(self, *replies: Any, default: Any = None) -> None:
        self._replies = list(replies)
        self._default = default
        self.calls: list[BackendCall] = []
        self.unloaded: list[str] = []

    async def _next(self, call: BackendCall) -> Any:
        self.calls.append(call)
        if self._replies:
            reply = self._replies.pop(0)
        elif self._default is not None:
            reply = self._default
        else:
            raise UnscriptedCallError(f"ScriptedBackend: no reply left for call #{len(self.calls)}")
        if callable(reply):
            reply = reply(call)
            if inspect.isawaitable(reply):
                reply = await reply
        return reply

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
        reply = await self._next(
            BackendCall(ref, messages, temperature, max_tokens, timeout_s, response_format, tools)
        )
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, RawCompletion):
            return reply
        return RawCompletion(text=str(reply), usage=Usage(prompt_tokens=10, completion_tokens=5))

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
        reply = await self._next(
            BackendCall(
                ref, messages, temperature, max_tokens, timeout_s, None, tools, streamed=True
            )
        )
        if isinstance(reply, BaseException):
            raise reply
        for piece in reply if isinstance(reply, list) else [reply]:
            if isinstance(piece, BaseException):
                raise piece
            if isinstance(piece, int | float):
                await asyncio.sleep(piece)
                continue
            yield piece if isinstance(piece, ChatChunk) else ChatChunk(delta=str(piece))

    async def unload(self, family: str) -> None:
        self.unloaded.append(family)
