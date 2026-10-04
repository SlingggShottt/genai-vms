"""FakeGateway — the test double other tracks build against."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel
from vms_common.llm import (
    ChatResult,
    ImageInput,
    LLMOutputError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
    ModelRegistry,
    ToolCall,
    ToolSpec,
)
from vms_common.llm.testing import FakeGateway, UnscriptedCallError

MODELS_YAML = Path(__file__).resolve().parents[4] / "config" / "models.yaml"


class Verdict(BaseModel):
    verdict: str
    confidence: float


IMG = ImageInput(data=b"\xff\xd8x")
GOOD = {"verdict": "confirmed", "confidence": 0.9}


async def test_a_scripted_dict_is_validated_into_the_response_model() -> None:
    gateway = FakeGateway({"event_verify": [GOOD]})
    result = await gateway.vision("event_verify", "is it real?", [IMG], response_model=Verdict)
    assert result.parsed == Verdict(verdict="confirmed", confidence=0.9)
    assert (result.provider, result.model, result.cached) == ("fake", "fake", False)


@pytest.mark.parametrize(
    "scripted",
    [
        json.dumps(GOOD),
        f"```json\n{json.dumps(GOOD)}\n```",
        Verdict(verdict="confirmed", confidence=0.9),
    ],
)
async def test_replies_may_be_text_fenced_text_or_a_model_instance(scripted) -> None:
    gateway = FakeGateway({"t": scripted})
    result = await gateway.chat("t", [Message(role="user", content="hi")], response_model=Verdict)
    assert result.parsed.verdict == "confirmed"


async def test_a_reply_that_would_not_validate_in_production_fails_here_too() -> None:
    gateway = FakeGateway({"t": {"verdict": "confirmed"}})  # confidence missing
    with pytest.raises(LLMOutputError, match="confidence") as caught:
        await gateway.chat("t", [{"role": "user", "content": "hi"}], response_model=Verdict)
    assert "confirmed" in caught.value.last_text


async def test_without_a_response_model_text_comes_back_raw() -> None:
    result = await FakeGateway({"t": "plain words"}).chat("t", [{"role": "user", "content": "x"}])
    assert (result.text, result.parsed) == ("plain words", None)


async def test_a_list_is_a_queue_and_running_out_fails_loudly() -> None:
    gateway = FakeGateway({"t": ["one", "two"]})
    msgs = [{"role": "user", "content": "x"}]
    assert (await gateway.chat("t", msgs)).text == "one"
    assert (await gateway.chat("t", msgs)).text == "two"
    with pytest.raises(UnscriptedCallError, match="used up"):
        await gateway.chat("t", msgs)


async def test_a_bare_value_answers_every_call() -> None:
    gateway = FakeGateway({"t": "same"})
    msgs = [{"role": "user", "content": "x"}]
    assert [(await gateway.chat("t", msgs)).text for _ in range(3)] == ["same"] * 3


async def test_an_unscripted_task_fails_loudly_instead_of_inventing_an_answer() -> None:
    with pytest.raises(UnscriptedCallError, match="no answer scripted for task 'other'"):
        await FakeGateway({"t": "x"}).chat("other", [{"role": "user", "content": "x"}])


async def test_exceptions_are_raised_in_order_with_successes() -> None:
    gateway = FakeGateway({"t": [LLMUnavailableError("gemini is down"), "recovered"]})
    msgs = [{"role": "user", "content": "x"}]
    with pytest.raises(LLMUnavailableError, match="gemini is down"):
        await gateway.chat("t", msgs)
    assert (await gateway.chat("t", msgs)).text == "recovered"


async def test_callables_see_the_call_and_can_answer_from_it() -> None:
    gateway = FakeGateway({"t": lambda call: f"echo: {call.prompt}"})
    result = await gateway.chat("t", [{"role": "user", "content": "ping"}])
    assert result.text == "echo: ping"


async def test_calls_are_recorded_for_assertions() -> None:
    gateway = FakeGateway({"event_verify": GOOD, "rerank": "x"})
    await gateway.vision(
        "event_verify", "verify this", [IMG, IMG], response_model=Verdict, system="be strict"
    )
    await gateway.chat("rerank", [{"role": "user", "content": "order these"}])
    (call,) = gateway.calls_for("event_verify")
    assert (call.method, call.prompt, len(call.images), call.response_model) == (
        "vision", "verify this", 2, Verdict,
    )  # fmt: skip
    assert call.messages[0] == Message(role="system", content="be strict")
    assert [c.task for c in gateway.calls] == ["event_verify", "rerank"]


async def test_tool_calls_can_be_scripted() -> None:
    tool = ToolCall(id="c1", name="count_objects", arguments={"camera": "cam01"})
    gateway = FakeGateway({"assistant": [tool, "There were 4 people."]})
    spec = ToolSpec(name="count_objects", description="count", parameters={"type": "object"})
    msgs = [{"role": "user", "content": "how many?"}]
    first = await gateway.chat("assistant", msgs, tools=[spec])
    assert first.tool_calls == [tool] and first.finish_reason == "tool_calls"
    assert gateway.calls[0].tools == [spec]
    assert (await gateway.chat("assistant", msgs, tools=[spec])).text == "There were 4 people."


async def test_a_chat_result_can_be_scripted_whole() -> None:
    canned = ChatResult(task="t", provider="gemini", model="flash", text="hi", cached=True)
    result = await FakeGateway({"t": canned}).chat("t", [{"role": "user", "content": "x"}])
    assert result is canned


async def test_streaming_yields_words_then_a_final_chunk() -> None:
    gateway = FakeGateway({"assistant": "three little words"})
    chunks = [
        c
        async for c in await gateway.chat(
            "assistant", [{"role": "user", "content": "x"}], stream=True
        )
    ]
    assert "".join(c.delta for c in chunks) == "three little words"
    assert chunks[-1].finish_reason == "stop" and chunks[-1].delta == ""
    assert len(chunks) == 4


async def test_the_same_argument_rules_as_the_real_gateway_apply() -> None:
    gateway = FakeGateway({"t": "x"})
    msgs = [{"role": "user", "content": "x"}]
    with pytest.raises(LLMRequestError, match="stream=True"):
        await gateway.chat("t", msgs, stream=True, response_model=Verdict)
    with pytest.raises(LLMRequestError, match="cannot be combined"):
        await gateway.chat(
            "t", msgs, response_model=Verdict, tools=[ToolSpec(name="f", description="d")]
        )
    with pytest.raises(LLMRequestError, match="empty"):
        await gateway.chat("t", [])
    with pytest.raises(LLMRequestError, match="at least one image"):
        await gateway.vision("t", "p", [])


async def test_with_a_registry_the_fake_enforces_modality_and_image_caps() -> None:
    registry = ModelRegistry.from_file(MODELS_YAML, profile="local")
    gateway = FakeGateway({"event_verify": GOOD, "rerank": "x"}, registry=registry)
    with pytest.raises(LLMRequestError, match="unknown task"):
        await gateway.chat("not_a_task", [{"role": "user", "content": "x"}])
    with pytest.raises(LLMRequestError, match="text-only"):
        await gateway.vision("rerank", "p", [IMG])
    with pytest.raises(LLMRequestError, match="cap of 4"):
        await gateway.vision("event_verify", "p", [IMG] * 5)
    assert (await gateway.vision("event_verify", "p", [IMG] * 4, response_model=Verdict)).parsed


def test_unused_reports_queued_answers_nobody_asked_for() -> None:
    gateway = FakeGateway({"a": ["1", "2"], "b": ["x"]})
    assert gateway.unused() == {"a": 2, "b": 1}


async def test_recordings_load_from_json_including_recorded_failures(tmp_path: Path) -> None:
    recording = tmp_path / "rec.json"
    recording.write_text(
        json.dumps(
            {
                "event_verify": [GOOD, {"$error": "timeout", "message": "VLM stalled"}],
                "rerank": {"ranking": [1, 2]},
                "assistant": [{"$error": "unavailable"}],
            }
        ),
        encoding="utf-8",
    )
    gateway = FakeGateway.from_recording(recording)
    first = await gateway.vision("event_verify", "p", [IMG], response_model=Verdict)
    assert first.parsed.verdict == "confirmed"
    with pytest.raises(LLMTimeoutError, match="VLM stalled"):
        await gateway.vision("event_verify", "p", [IMG])
    assert json.loads((await gateway.chat("rerank", [{"role": "user", "content": "x"}])).text) == {
        "ranking": [1, 2]
    }
    with pytest.raises(LLMUnavailableError, match="recorded unavailable error"):
        await gateway.chat("assistant", [{"role": "user", "content": "x"}])


def test_a_recording_with_an_unknown_error_kind_is_rejected(tmp_path: Path) -> None:
    recording = tmp_path / "rec.json"
    recording.write_text(json.dumps({"t": {"$error": "meltdown"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown recorded"):
        FakeGateway.from_recording(recording)
    recording.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        FakeGateway.from_recording(recording)
