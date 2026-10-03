"""The VQA question bank (P3-J6): the questions asked about one phase of an incident in one view.

`config/vqa_bank.yaml` is the one source for what the PhaVR evidence step asks, what annotators
verify in the caption/VQA labelling template, and what the adapter is scored on. This module reads
it and refuses a bank that would quietly mislabel data: too few or too many questions for an event
type, a question id used twice, a choice with one option, an id that does not belong to its event
type. Labelled data refers to question ids, so those rules are checked here rather than trusted.

Every question also accepts `CANNOT_TELL`, which is not listed in the file: an annotator never has
to guess, and a model that cannot see the answer is scored on honesty rather than luck.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CANNOT_TELL = "Cannot tell"
YES = "Yes"
NO = "No"
DEFAULT_EVENT_TYPE = "default"
MIN_QUESTIONS = 5
MAX_QUESTIONS = 8
MIN_OPTIONS = 2
MAX_OPTIONS = 6

_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*$")


class VQAQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    text: str = Field(min_length=1)
    kind: Literal["yes_no", "choice"]
    options: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def _id_has_the_expected_shape(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError(
                f"id {value!r} must look like '<event_type>.<name>' in lower snake case"
            )
        return value

    @field_validator("text")
    @classmethod
    def _text_is_a_question(cls, value: str) -> str:
        if not value.endswith("?"):
            raise ValueError(f"{value!r} must be phrased as a question and end with '?'")
        return value

    @model_validator(mode="after")
    def _options_match_the_kind(self) -> Self:
        if self.kind == "yes_no":
            if self.options:
                raise ValueError(
                    f"{self.id}: a yes_no question has no options (the answers are Yes and No)"
                )
            return self
        if not MIN_OPTIONS <= len(self.options) <= MAX_OPTIONS:
            raise ValueError(
                f"{self.id}: a choice needs {MIN_OPTIONS} to {MAX_OPTIONS} options, "
                f"got {len(self.options)}"
            )
        folded = [option.strip().casefold() for option in self.options]
        if any(not option for option in folded):
            raise ValueError(f"{self.id}: an option must not be empty")
        if len(set(folded)) != len(folded):
            raise ValueError(f"{self.id}: options must be different from each other")
        if CANNOT_TELL.casefold() in folded:
            raise ValueError(f"{self.id}: {CANNOT_TELL!r} is always allowed, so it is not listed")
        return self

    @property
    def answers(self) -> tuple[str, ...]:
        """Every answer this question accepts, `CANNOT_TELL` last."""
        base = (YES, NO) if self.kind == "yes_no" else self.options
        return (*base, CANNOT_TELL)


class VQABank(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    event_types: dict[str, tuple[VQAQuestion, ...]]

    @model_validator(mode="after")
    def _the_bank_is_consistent(self) -> Self:
        if DEFAULT_EVENT_TYPE not in self.event_types:
            raise ValueError(
                f"the bank needs a {DEFAULT_EVENT_TYPE!r} set for event types it does not know"
            )
        seen: dict[str, str] = {}
        for event_type, questions in self.event_types.items():
            if not _EVENT_TYPE.match(event_type):
                raise ValueError(f"event type {event_type!r} must be lower snake case")
            if not MIN_QUESTIONS <= len(questions) <= MAX_QUESTIONS:
                raise ValueError(
                    f"{event_type}: {MIN_QUESTIONS} to {MAX_QUESTIONS} questions are required, "
                    f"got {len(questions)}"
                )
            for question in questions:
                prefix = question.id.split(".", 1)[0]
                if prefix != event_type:
                    raise ValueError(
                        f"{question.id} is under {event_type!r} but its id says {prefix!r}"
                    )
                if question.id in seen:
                    raise ValueError(f"question id {question.id} appears twice")
                seen[question.id] = event_type
        return self

    def questions_for(self, event_type: str) -> tuple[VQAQuestion, ...]:
        """The questions for `event_type`, or the `default` set when it has none of its own."""
        return self.event_types.get(event_type) or self.event_types[DEFAULT_EVENT_TYPE]

    def question(self, question_id: str) -> VQAQuestion:
        """One question by id, wherever it is. `KeyError` for an id the bank does not have."""
        for questions in self.event_types.values():
            for question in questions:
                if question.id == question_id:
                    return question
        raise KeyError(question_id)


def parse_vqa_bank(data: Mapping[str, Any]) -> VQABank:
    return VQABank.model_validate(data)


def load_vqa_bank(path: str | Path) -> VQABank:
    """Read and check a bank file (normally `config/vqa_bank.yaml`)."""
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return parse_vqa_bank(data)
