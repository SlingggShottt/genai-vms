"""LLMGateway: provider-agnostic chat/vision calls with response_model validation, a model
registry (config/models.yaml), a Redis GPU lease, a response cache and versioned prompts
(design_architecture.md §11, story P3-D3).

    from vms_common.llm import LLMGateway, render_prompt

    gateway = LLMGateway.from_settings()
    prompt = render_prompt("event_verify", "1.0", ...)
    result = await gateway.vision("event_verify", prompt, images, response_model=Verdict)

Tests use `vms_common.llm.testing.FakeGateway`. Needs the `llm` extra of vms-common
(`vms-common[llm]`: litellm, pillow, jinja2, pyyaml, httpx).
"""

from vms_common.llm.errors import (
    GPULeaseTimeoutError,
    LLMError,
    LLMOutputError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelRegistryError,
)
from vms_common.llm.gateway import Gateway, LLMGateway
from vms_common.llm.prompts import PromptLibrary, render_prompt
from vms_common.llm.registry import ModelRef, ModelRegistry, TaskConfig
from vms_common.llm.types import (
    ChatChunk,
    ChatResult,
    ImageInput,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)

__all__ = [
    "ChatChunk",
    "ChatResult",
    "GPULeaseTimeoutError",
    "Gateway",
    "ImageInput",
    "LLMError",
    "LLMGateway",
    "LLMOutputError",
    "LLMRequestError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "Message",
    "ModelRef",
    "ModelRegistry",
    "ModelRegistryError",
    "PromptLibrary",
    "TaskConfig",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "render_prompt",
]
