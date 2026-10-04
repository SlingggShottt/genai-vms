"""Structured output: extracting JSON from messy replies, validating, repair messages."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, Field
from vms_common.llm.structured import (
    describe_error,
    extract_json,
    parse_structured,
    repair_messages,
    response_format_for,
)


class Verdict(BaseModel):
    verdict: Literal["confirmed", "rejected"]
    confidence: float = Field(ge=0, le=1)
    reason: str


GOOD = '{"verdict": "confirmed", "confidence": 0.9, "reason": "person in zone"}'


@pytest.mark.parametrize(
    "reply",
    [
        GOOD,
        f"  \n{GOOD}\n ",
        f"```json\n{GOOD}\n```",
        f"```\n{GOOD}\n```",
        f"Sure! Here is the JSON:\n```json\n{GOOD}\n```\nHope that helps.",
        f"The verdict is below.\n{GOOD}\nLet me know if you need more.",
        f"<think>maybe {{rejected}}? no.</think>\n{GOOD}",
        f"First {{note}} then {GOOD}",  # a brace in prose must not hide the real object
    ],
)
def test_extract_json_finds_the_object_however_it_is_wrapped(reply: str) -> None:
    assert parse_structured(reply, Verdict).verdict == "confirmed"


def test_a_json_array_inside_prose_is_found() -> None:
    assert extract_json("The track ids are [4, 7, 9] as listed.") == [4, 7, 9]


def test_a_fenced_block_wins_over_json_that_appears_earlier_in_the_prose() -> None:
    reply = f'For example {{"verdict": "rejected"}} would mean no.\n```json\n{GOOD}\n```'
    assert parse_structured(reply, Verdict).verdict == "confirmed"


def test_extract_json_returns_arrays_and_nested_values_intact() -> None:
    assert extract_json('[{"a": [1, 2, {"b": 3}]}]') == [{"a": [1, 2, {"b": 3}]}]
    assert extract_json('noise {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}


@pytest.mark.parametrize(
    "reply", ["", "   ", "I cannot help with that.", "{unterminated", "<think>{}</think>"]
)
def test_extract_json_raises_value_error_when_there_is_no_json(reply: str) -> None:
    with pytest.raises(ValueError, match="no JSON"):
        extract_json(reply)


def test_parse_structured_rejects_json_that_does_not_match_the_model() -> None:
    with pytest.raises(ValueError, match="verdict"):
        parse_structured('{"verdict": "maybe", "confidence": 0.5, "reason": "x"}', Verdict)
    with pytest.raises(ValueError, match="confidence"):
        parse_structured('{"verdict": "confirmed", "confidence": 7, "reason": "x"}', Verdict)
    with pytest.raises(ValueError, match="reason"):
        parse_structured('{"verdict": "confirmed", "confidence": 0.5}', Verdict)


def test_describe_error_names_the_fields_without_echoing_a_rejected_value() -> None:
    sentinel = "card-4111-1111-1111-1111"
    with pytest.raises(ValueError) as caught:
        parse_structured(f'{{"verdict": "{sentinel}", "confidence": 0.5, "reason": "x"}}', Verdict)
    text = describe_error(caught.value)
    assert "verdict" in text
    assert sentinel not in text
    assert "http" not in text  # no pydantic docs URL either


def test_describe_error_is_bounded() -> None:
    class Wide(BaseModel):
        items: list[int]

    with pytest.raises(ValueError) as caught:
        parse_structured('{"items": ' + str(["x"] * 400).replace("'", '"') + "}", Wide)
    assert len(describe_error(caught.value)) <= 600


def test_describe_error_handles_a_plain_value_error() -> None:
    assert describe_error(ValueError("the reply contains no JSON object")) == (
        "the reply contains no JSON object"
    )


def test_response_format_carries_the_models_json_schema() -> None:
    fmt = response_format_for(Verdict)
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "Verdict"
    assert fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema["properties"]["verdict"]["enum"] == ["confirmed", "rejected"]
    assert set(schema["required"]) == {"verdict", "confidence", "reason"}


def test_repair_messages_show_the_model_its_reply_and_the_errors() -> None:
    messages = repair_messages("garbage", "verdict: Input should be 'confirmed'")
    assert messages[0] == {"role": "assistant", "content": "garbage"}
    assert messages[1]["role"] == "user"
    assert "verdict: Input should be 'confirmed'" in messages[1]["content"]
    assert "ONLY one JSON object" in messages[1]["content"]
