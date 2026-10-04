"""Value types of the gateway interface (design_architecture.md §11.1).

These cross the gateway's public boundary (callers build `Message`s and read
`ChatResult`s) so they are Pydantic models; none of them is a Kafka or HTTP
payload, so they carry no `schema_version`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolSpec(BaseModel):
    """A function the model may call. `parameters` is a JSON Schema object."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class ToolCall(BaseModel):
    """A model's request to call a tool. `arguments` is already parsed."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """One chat turn. An assistant turn that only calls tools has `content=None`."""

    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None  # role == "assistant"
    tool_call_id: str | None = None  # role == "tool": which call this answers
    name: str | None = None  # role == "tool": the tool's name


class ImageInput(BaseModel):
    """An encoded image (JPEG/PNG/WebP bytes) for `LLMGateway.vision`."""

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    data: bytes
    mime: Literal["image/jpeg", "image/png", "image/webp"] = "image/jpeg"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ChatResult(BaseModel):
    """What a call returned, plus where it came from (provenance for reports)."""

    task: str
    provider: str
    model: str
    text: str
    parsed: Any | None = None  # an instance of `response_model` when one was given
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str | None = None
    latency_s: float = 0.0
    cached: bool = False
    # Model calls spent on this result: validation retries and fallbacks count.
    attempts: int = 1
    # 0 = the task's primary model answered; 1.. = that many fallbacks were needed.
    fallback_index: int = 0


class ChatChunk(BaseModel):
    """One streamed piece. The last chunk carries `finish_reason`, `usage`, `tool_calls`."""

    delta: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None
