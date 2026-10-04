"""Draft captions and VQA answers for people to verify (the pseudo-labelling step).

The model drafts, a person verifies: PhaVR's training labels are human-checked, but writing every
caption from nothing is slow and checking a draft is fast. This module is the part that needs no GPU
and no model: it builds the prompt, reads what the model said, and turns it into Label Studio
*predictions* (pre-annotations) that appear filled in for the annotator. The model itself is a plain
callable, so the Kaggle notebook plugs in Qwen2.5-VL-7B and the tests plug in a fake.

A draft that cannot be read, or an answer that is not one of the allowed ones, never becomes a
confident wrong label: it becomes "Cannot tell" and is counted, so the person sees an honest blank
rather than a guess, and the numbers say how often it happened.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from string import Template
from typing import Any, Protocol

from vms_common.vqa_bank import CANNOT_TELL, NO, YES, VQABank, VQAQuestion

from annotation_kit.labelconfig import CAPTION, VIDEO
from annotation_kit.phases import PHASE_DEFINITIONS
from annotation_kit.schema import CaptionVqaTask

PROMPT_VERSION = "prelabel/1.0"


class PreLabeler(Protocol):
    """Anything that turns a task and its prompt into the model's raw text."""

    def __call__(self, task: CaptionVqaTask, prompt: str) -> str: ...


def load_prompt() -> Template:
    text = resources.files("annotation_kit.prompts").joinpath("prelabel_1.0.md").read_text("utf-8")
    return Template(text)


def render_questions(questions: Sequence[VQAQuestion]) -> str:
    return "\n".join(
        f"- {question.id}: {question.text} Answers: {' | '.join(question.answers)}"
        for question in questions
    )


def render_prompt(task: CaptionVqaTask, questions: Sequence[VQAQuestion]) -> str:
    return load_prompt().substitute(
        event_type=task.event_type.replace("_", " "),
        view=task.view,
        phase=task.phase,
        phase_definition=PHASE_DEFINITIONS[task.phase],
        start_s=f"{task.start_s:g}",
        end_s=f"{task.end_s:g}",
        questions=render_questions(questions),
    )


@dataclass(frozen=True)
class Draft:
    caption: str
    answers: dict[str, str]  # one entry for every question
    problems: tuple[str, ...] = ()  # what was wrong with the model's reply, in words
    unparseable: bool = False
    coerced: tuple[str, ...] = field(
        default=()
    )  # ids answered "Cannot tell" only because of a problem


def _first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _end = decoder.raw_decode(text[match.start() :])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _match_answer(raw: object, question: VQAQuestion) -> str | None:
    if isinstance(raw, bool) and question.kind == "yes_no":
        return YES if raw else NO
    if not isinstance(raw, str):
        return None
    wanted = raw.strip().strip("\"'").rstrip(".").strip().casefold()
    return next((answer for answer in question.answers if answer.casefold() == wanted), None)


def parse_draft(raw: str, questions: Sequence[VQAQuestion]) -> Draft:
    """Read the model's reply. Always returns an answer for every question."""
    blank = {question.id: CANNOT_TELL for question in questions}
    data = _first_json_object(raw)
    if data is None:
        return Draft(
            caption="",
            answers=blank,
            problems=("the reply contained no JSON object",),
            unparseable=True,
            coerced=tuple(blank),
        )

    problems: list[str] = []
    raw_caption = data.get("caption")
    caption = " ".join(raw_caption.split()) if isinstance(raw_caption, str) else ""
    if not caption:
        problems.append("no caption")

    given = data.get("answers")
    given = given if isinstance(given, Mapping) else {}
    if not isinstance(data.get("answers"), Mapping):
        problems.append("no answers object")
    answers: dict[str, str] = {}
    coerced: list[str] = []
    for question in questions:
        if question.id not in given:
            problems.append(f"{question.id}: no answer")
            answers[question.id] = CANNOT_TELL
            coerced.append(question.id)
            continue
        matched = _match_answer(given[question.id], question)
        if matched is None:
            problems.append(f"{question.id}: {given[question.id]!r} is not an allowed answer")
            answers[question.id] = CANNOT_TELL
            coerced.append(question.id)
        else:
            answers[question.id] = matched
    return Draft(caption=caption, answers=answers, problems=tuple(problems), coerced=tuple(coerced))


def prediction_result(draft: Draft, questions: Sequence[VQAQuestion]) -> list[dict[str, Any]]:
    """The draft as Label Studio `result` items, naming the controls of the generated config."""
    result: list[dict[str, Any]] = []
    if draft.caption:
        result.append(
            {
                "from_name": CAPTION,
                "to_name": VIDEO,
                "type": "textarea",
                "value": {"text": [draft.caption]},
            }
        )
    for question in questions:
        result.append(
            {
                "from_name": question.id,
                "to_name": VIDEO,
                "type": "choices",
                "value": {"choices": [draft.answers[question.id]]},
            }
        )
    return result


@dataclass
class PrelabelStats:
    tasks: int = 0
    unparseable: int = 0  # replies with no JSON at all: the annotator starts from a blank
    without_caption: int = 0
    coerced_answers: int = 0  # answers that became "Cannot tell" because of a problem
    answers: int = 0

    @property
    def coerced_rate(self) -> float:
        return self.coerced_answers / self.answers if self.answers else 0.0


def preannotate(
    tasks: Iterable[CaptionVqaTask],
    bank: VQABank,
    labeler: PreLabeler,
    *,
    model_version: str,
) -> tuple[list[dict[str, Any]], PrelabelStats]:
    """Label Studio import items (`data` + `predictions`) for every task, and how it went."""
    stats = PrelabelStats()
    items: list[dict[str, Any]] = []
    for task in tasks:
        questions = bank.questions_for(task.event_type)
        draft = parse_draft(labeler(task, render_prompt(task, questions)), questions)
        stats.tasks += 1
        stats.answers += len(questions)
        stats.coerced_answers += len(draft.coerced)
        stats.unparseable += draft.unparseable
        stats.without_caption += not draft.caption
        item: dict[str, Any] = {"data": task.model_dump(), "predictions": []}
        if not draft.unparseable:
            item["predictions"].append(
                {
                    "model_version": model_version,
                    "result": prediction_result(draft, questions),
                }
            )
        items.append(item)
    return items, stats
