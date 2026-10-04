"""Gateway exceptions.

Callers handle three situations differently (style_guide.md §A.5 status codes):

- `LLMUnavailableError` — the model could not be reached or did not answer in time
  (provider down, rate limited, GPU busy, timeout). Retry later / degrade → 503.
- `LLMOutputError` — a model answered but never produced output that validates
  against `response_model`, even after repair retries → 422.
- `LLMRequestError` — the *caller* asked for something the registry cannot do
  (unknown task, too many images, `vision` on a text task). A bug, not an outage.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for everything the gateway raises on purpose."""


class LLMRequestError(LLMError, ValueError):
    """The call itself is wrong (unknown task, image cap, wrong modality)."""


class ModelRegistryError(LLMError, ValueError):
    """`models.yaml` is invalid. Raised at load, so a typo stops startup, not a request."""


class LLMUnavailableError(LLMError):
    """No candidate model answered. `failures` lists what happened to each, in order."""

    def __init__(self, message: str, *, failures: list[str] | None = None) -> None:
        super().__init__(message)
        self.failures = failures or []


class LLMTimeoutError(LLMUnavailableError):
    """A model did not answer within the task's timeout."""


class GPULeaseTimeoutError(LLMUnavailableError):
    """Another model family held the GPU for longer than the caller was willing to queue."""


class LLMOutputError(LLMError):
    """Output never validated against `response_model`. `last_text` is the final reply."""

    def __init__(
        self, message: str, *, last_text: str = "", failures: list[str] | None = None
    ) -> None:
        super().__init__(message)
        self.last_text = last_text
        self.failures = failures or []
