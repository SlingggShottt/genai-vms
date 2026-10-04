"""Structured output: ask for JSON, extract it from whatever the model wrapped it in,
validate it against the caller's Pydantic model, and build the "try again" message.

Small local models routinely wrap JSON in ``` fences, prepend a sentence, or emit a
`<think>` block first; none of that should cost a retry. What *does* cost one is JSON that
parses but does not validate (missing field, wrong enum value) — the gateway then shows the
model its own reply and the validation errors once more (see `repair_messages`).
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_MAX_ERROR_CHARS = 600


def extract_json(text: str) -> Any:
    """Return the first JSON value in `text`. Raises `ValueError` when there is none."""
    cleaned = _THINK.sub("", text).strip()
    try:
        return json.loads(cleaned)  # the common case: the reply is exactly the JSON
    except ValueError:
        pass

    sources = [cleaned]
    fenced = _FENCE.search(cleaned)
    if fenced:
        sources.insert(0, fenced.group(1).strip())

    decoder = json.JSONDecoder()
    for source in sources:
        for start, char in enumerate(source):
            if char not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(source, start)
            except ValueError:
                continue  # that brace was prose ("{name}"), keep scanning
            return value
    raise ValueError("the reply contains no JSON object")


def parse_structured(text: str, model: type[T]) -> T:
    """Extract and validate. Raises `ValueError` (`ValidationError` is one) on any failure."""
    return model.model_validate(extract_json(text))


def describe_error(exc: ValueError) -> str:
    """A short, input-free description of why a reply was rejected."""
    if isinstance(exc, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        ]
        text = "; ".join(parts)
    else:
        text = str(exc)
    return text[:_MAX_ERROR_CHARS]


def response_format_for(model: type[BaseModel]) -> dict[str, Any]:
    """OpenAI-style `response_format`. LiteLLM turns it into the provider's native form
    (Ollama `format`, Gemini `responseSchema`); where a provider has none it drops it and
    the validate-and-retry loop is the only guard."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "schema": model.model_json_schema(),
            "strict": True,
        },
    }


def repair_messages(bad_reply: str, error: str) -> list[dict[str, str]]:
    """Messages appended to the conversation to ask for a corrected reply."""
    return [
        {"role": "assistant", "content": bad_reply},
        {
            "role": "user",
            "content": (
                f"Your previous reply was rejected: {error}. "
                "Reply again with ONLY one JSON object that matches the required schema — "
                "no commentary, no code fences."
            ),
        },
    ]
