"""Shared builders, as fixtures (the repo's pytest runs in importlib mode: no sibling imports)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from annotation_kit.labelconfig import CAPTION, USABLE, VIDEO
from annotation_kit.schema import CaptionVqaTask, PhaseLabelClip
from vms_common.vqa_bank import VQABank, VQAQuestion, load_vqa_bank

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO


@pytest.fixture(scope="session")
def bank() -> VQABank:
    return load_vqa_bank(REPO / "config/vqa_bank.yaml")


@pytest.fixture
def make_task() -> Callable[..., CaptionVqaTask]:
    def make(**over: Any) -> CaptionVqaTask:
        fields: dict[str, Any] = {
            "clip_id": "clip-1",
            "source_video": "source-1",
            "event_type": "intrusion",
            "view": "cam02",
            "phase": "precursor",
            "start_s": 3.5,
            "end_s": 9.0,
            "video_uri": "s3://vms-evidence/clips/clip-1/cam02.mp4",
            "video": "https://media.example/clips/clip-1/cam02.mp4#t=3.5,9",
        }
        fields.update(over)
        return CaptionVqaTask(**fields)

    return make


@pytest.fixture
def make_clip() -> Callable[..., PhaseLabelClip]:
    def make(**over: Any) -> PhaseLabelClip:
        fields: dict[str, Any] = {
            "clip_id": "clip-1",
            "source_video": "source-1",
            "event_type": "intrusion",
            "primary_view": "cam02",
            "views": [
                {"camera": "cam04", "video_uri": "s3://b/clip-1/cam04.mp4"},
                {"camera": "cam02", "video_uri": "s3://b/clip-1/cam02.mp4"},
            ],
            "phases": [
                {"phase": "baseline", "start_s": 0, "end_s": 3.5},
                {"phase": "precursor", "start_s": 3.5, "end_s": 9},
            ],
            "annotator": "K",
        }
        fields.update(over)
        return PhaseLabelClip(**fields)

    return make


def first_answers(questions: Sequence[VQAQuestion]) -> dict[str, str]:
    return {q.id: q.answers[0] for q in questions}


@pytest.fixture
def answers_for() -> Callable[[Sequence[VQAQuestion]], dict[str, str]]:
    return first_answers


@pytest.fixture
def ls_result() -> Callable[..., list[dict[str, Any]]]:
    """A Label Studio `result` list: a caption, one answer per control, and optionally `usable`."""

    def build(
        caption: str | None, answers: dict[str, str], usable: str | None = None
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if caption is not None:
            result.append(
                {
                    "from_name": CAPTION,
                    "to_name": VIDEO,
                    "type": "textarea",
                    "value": {"text": [caption]},
                }
            )
        for name, answer in answers.items():
            result.append(
                {
                    "from_name": name,
                    "to_name": VIDEO,
                    "type": "choices",
                    "value": {"choices": [answer]},
                }
            )
        if usable is not None:
            result.append(
                {
                    "from_name": USABLE,
                    "to_name": VIDEO,
                    "type": "choices",
                    "value": {"choices": [usable]},
                }
            )
        return result

    return build
