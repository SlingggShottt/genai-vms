"""The evidence step's reading of the vision model's answer: what survives `clean_answers`.

The recorded answers below are real: `qwen2.5vl:3b` through the gateway on 2026-10-06 (a PhaVR
evaluation plumbing run), including its habit of copying the prompt's `[id]` brackets into the id.
Before the fix 31 of 38 stored views had lost every answer to it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from reasoning.adapters.footage import FootFrame
from reasoning.adapters.store import EventInfo
from reasoning.domain.context import build_context
from reasoning.steps.readings import ViewDraft, clean_answers, read_view
from vms_common.contracts.reasoning import PhaseSpan
from vms_common.llm.testing import FakeGateway
from vms_common.vqa_bank import load_vqa_bank

BANK = load_vqa_bank(Path(__file__).resolve().parents[4] / "config" / "vqa_bank.yaml")
QUESTIONS = list(BANK.questions_for("intrusion"))

# What the model said for one view, ids and all (recorded).
RECORDED = {
    "caption": "A person is walking along the edge of a restricted area, carrying an item.",
    "answers": [
        {"id": "[intrusion.crossing_barrier]", "answer": "Yes"},
        {"id": "[intrusion.inside_restricted_area]", "answer": "No"},
        {"id": "[intrusion.carrying_item]", "answer": "Yes"},
        {"id": "[intrusion.staff_visible]", "answer": "No"},
        {"id": "[intrusion.direction]", "answer": "Along its edge"},
        {"id": "[intrusion.person_count]", "answer": "1"},
        {"id": "[intrusion.area_lit]", "answer": "Cannot tell"},
        {"id": "[intrusion.leaves_view]", "answer": "No"},
    ],
}


def draft(*answers: tuple[str, str]) -> ViewDraft:
    return ViewDraft.model_validate(
        {"caption": "c", "answers": [{"id": i, "answer": a} for i, a in answers]}
    )


def test_a_recorded_answer_with_bracketed_ids_keeps_every_answer() -> None:
    cleaned = clean_answers(ViewDraft.model_validate(RECORDED), QUESTIONS)
    assert [(i, v) for i, _, v in cleaned] == [
        ("intrusion.crossing_barrier", "Yes"),
        ("intrusion.inside_restricted_area", "No"),
        ("intrusion.carrying_item", "Yes"),
        ("intrusion.staff_visible", "No"),
        ("intrusion.direction", "Along its edge"),
        ("intrusion.person_count", "1"),
        ("intrusion.area_lit", "Cannot tell"),
        ("intrusion.leaves_view", "No"),
    ]
    assert all(text.endswith("?") for _, text, _ in cleaned)  # each carries the question's own text


@pytest.mark.parametrize(
    "raw",
    [
        "intrusion.area_lit",
        "[intrusion.area_lit]",
        "  [intrusion.area_lit] ",
        "`intrusion.area_lit`",
        "'intrusion.area_lit'",
        '"intrusion.area_lit"',
        "(intrusion.area_lit)",
    ],
)
def test_formatting_around_the_id_is_ignored(raw: str) -> None:
    [(qid, _, value)] = clean_answers(draft((raw, "Yes")), QUESTIONS)
    assert (qid, value) == ("intrusion.area_lit", "Yes")


def test_answers_are_matched_to_the_vocabulary_ignoring_case_and_a_final_stop() -> None:
    cleaned = clean_answers(
        draft(("intrusion.area_lit", "yes."), ("intrusion.staff_visible", "NO")), QUESTIONS
    )
    assert [(i, v) for i, _, v in cleaned] == [
        ("intrusion.area_lit", "Yes"),
        ("intrusion.staff_visible", "No"),
    ]


def test_what_is_not_evidence_is_still_dropped() -> None:
    cleaned = clean_answers(
        draft(
            ("intrusion.area_lit", "Probably"),  # outside the vocabulary
            ("intrusion.no_such_question", "Yes"),  # never asked
            ("[intrusion.staff_visible]", "No"),
            ("intrusion.staff_visible", "Yes"),  # the same question twice: the first one stands
            ("", "Yes"),
        ),
        QUESTIONS,
    )
    assert [(i, v) for i, _, v in cleaned] == [("intrusion.staff_visible", "No")]


def test_only_the_edges_of_an_id_are_stripped() -> None:
    assert clean_answers(draft(("intrusion.area[lit]", "Yes")), QUESTIONS) == []


class _Footage:
    async def image(self, uri: str) -> bytes:
        return b"jpeg"


async def test_read_view_keeps_the_answers_a_model_gives_with_bracketed_ids() -> None:
    t0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    event = EventInfo(
        id="e1", camera_id="cam02", event_type="intrusion", severity="high",
        rule_id="intrusion.restricted", zone_name=None, start=t0 + timedelta(seconds=10),
        end=t0 + timedelta(seconds=16), status="verified", caption=None, confidence=0.9,
    )  # fmt: skip
    ctx = build_context([event], group_id=None, pad_before_s=10, pad_after_s=10, max_views=2)
    frames = [FootFrame("cam02", t0 + timedelta(seconds=k), f"u{k}") for k in range(27)]
    span = PhaseSpan(
        phase="action", start=t0 + timedelta(seconds=8), end=t0 + timedelta(seconds=12), source="x"
    )
    gateway = FakeGateway({"phase_vr": RECORDED})
    reading = await read_view(
        gateway, _Footage(), ctx, span, "cam02", frames, QUESTIONS, n_frames=2
    )
    assert reading is not None and len(reading.answers) == 8
    assert reading.caption.startswith("A person is walking along the edge")
