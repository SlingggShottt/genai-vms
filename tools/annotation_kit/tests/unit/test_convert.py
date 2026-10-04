from __future__ import annotations

import json
from pathlib import Path

import pytest
from annotation_kit.convert import (
    SKIP_REASONS,
    convert,
    normalise,
    read_export,
    similarity,
    write_jsonl,
)
from annotation_kit.schema import PhavrLabel
from vms_common.vqa_bank import CANNOT_TELL, VQABank

DRAFT_CAPTION = "A person walks along the fence and looks around."


@pytest.fixture
def questions(bank: VQABank):  # noqa: ANN201
    return bank.questions_for("intrusion")


@pytest.fixture
def item(make_task, ls_result, answers_for, questions):  # noqa: ANN001, ANN201
    """A Label Studio export item with a draft and a finished annotation that accepts it."""

    def build(
        *,
        caption: str | None = DRAFT_CAPTION,
        draft_caption: str = DRAFT_CAPTION,
        answers: dict[str, str] | None = None,
        draft_answers: dict[str, str] | None = None,
        usable: str | None = "Yes",
        predictions: bool = True,
        annotations: list[dict] | None = None,
        task_over: dict | None = None,
    ) -> dict:
        base = answers_for(questions)
        done = {**base, **(answers or {})}
        drafted = {**base, **(draft_answers or {})}
        item: dict = {"id": 1, "data": make_task(**(task_over or {})).model_dump()}
        item["annotations"] = (
            annotations
            if annotations is not None
            else [
                {
                    "id": 10,
                    "completed_by": {"id": 3, "email": "k@example.com"},
                    "was_cancelled": False,
                    "updated_at": "2026-10-05T10:00:00Z",
                    "result": ls_result(caption, done, usable),
                }
            ]
        )
        item["predictions"] = (
            [
                {
                    "model_version": "qwen2.5-vl-7b@prelabel-1.0",
                    "result": ls_result(draft_caption, drafted),
                }
            ]
            if predictions
            else []
        )
        return item

    return build


class TestNormalisingText:
    def test_case_punctuation_and_spacing_are_not_edits(self) -> None:
        assert normalise("  A person   walks, by!  ") == normalise("a person walks by")

    def test_words_are_edits(self) -> None:
        assert normalise("A person walks") != normalise("A person runs")

    def test_similarity_runs_from_one_to_zero(self) -> None:
        assert similarity("A person walks by.", "a person walks by") == 1.0
        assert similarity("abc def", "xyz uvw") == 0.0
        assert 0 < similarity("a person walks by the gate", "a person runs by the gate") < 1

    def test_two_empty_captions_are_identical_and_one_empty_is_not(self) -> None:
        assert similarity("", "...") == 1.0
        assert similarity("", "A person.") == 0.0


class TestAcceptingADraft:
    def test_an_accepted_draft_is_an_untouched_label(self, item, bank: VQABank, questions) -> None:  # noqa: ANN001
        converted = convert([item()], bank)
        label = converted.labels[0]
        assert not converted.skipped
        assert label.caption == DRAFT_CAPTION
        assert label.edits is not None
        assert label.edits.caption_changed is False
        assert label.edits.caption_similarity == 1.0
        assert label.edits.answers_changed == []
        assert label.annotator == "k@example.com"

    def test_the_label_describes_where_it_comes_from(self, item, bank: VQABank) -> None:  # noqa: ANN001
        label = convert([item()], bank).labels[0]
        assert (label.clip_id, label.source_video, label.view, label.phase) == (
            "clip-1",
            "source-1",
            "cam02",
            "precursor",
        )
        assert (label.event_type, label.start_s, label.end_s) == ("intrusion", 3.5, 9.0)
        assert label.schema_version == "phavr_label.v1"

    def test_vqa_follows_the_banks_order_with_each_questions_text(
        self, item, bank: VQABank, questions
    ) -> None:  # noqa: ANN001
        label = convert([item()], bank).labels[0]
        assert [v.id for v in label.vqa] == [q.id for q in questions]
        assert [v.q for v in label.vqa] == [q.text for q in questions]
        assert all(v.a == q.answers[0] for v, q in zip(label.vqa, questions, strict=True))

    def test_the_draft_is_kept_beside_the_label(self, item, bank: VQABank, questions) -> None:  # noqa: ANN001
        label = convert([item()], bank).labels[0]
        assert label.pseudo is not None
        assert label.pseudo.model_version == "qwen2.5-vl-7b@prelabel-1.0"
        assert label.pseudo.caption == DRAFT_CAPTION
        assert set(label.pseudo.vqa) == {q.id for q in questions}


class TestEditing:
    def test_a_rewritten_caption_is_a_caption_edit_with_a_lower_similarity(
        self, item, bank: VQABank
    ) -> None:  # noqa: ANN001
        label = convert([item(caption="A man in a dark coat climbs the gate.")], bank).labels[0]
        assert label.edits is not None
        assert label.edits.caption_changed is True
        assert 0 <= label.edits.caption_similarity < 0.6
        assert label.caption == "A man in a dark coat climbs the gate."

    def test_adding_a_full_stop_and_a_capital_is_not_an_edit(self, item, bank: VQABank) -> None:  # noqa: ANN001
        label = convert(
            [item(caption="a person walks along the fence and looks around")], bank
        ).labels[0]
        assert label.edits is not None and label.edits.caption_changed is False

    def test_a_changed_answer_is_listed_by_question_id(
        self, item, bank: VQABank, questions
    ) -> None:  # noqa: ANN001
        label = convert([item(answers={questions[0].id: "No"})], bank).labels[0]
        assert label.edits is not None
        assert label.edits.answers_changed == [questions[0].id]
        assert label.edits.caption_changed is False

    def test_several_changed_answers_come_back_in_banks_order(
        self, item, bank: VQABank, questions
    ) -> None:  # noqa: ANN001
        changed = {questions[3].id: "No", questions[1].id: "No"}
        label = convert([item(answers=changed)], bank).labels[0]
        assert label.edits is not None
        assert label.edits.answers_changed == [questions[1].id, questions[3].id]

    def test_an_answer_the_model_never_gave_counts_as_changed(
        self, item, bank: VQABank, questions
    ) -> None:  # noqa: ANN001
        raw = item()
        raw["predictions"][0]["result"] = [
            r for r in raw["predictions"][0]["result"] if r["from_name"] != questions[2].id
        ]
        label = convert([raw], bank).labels[0]
        assert label.edits is not None and label.edits.answers_changed == [questions[2].id]

    def test_an_empty_draft_caption_is_replaced_not_accepted(self, item, bank: VQABank) -> None:  # noqa: ANN001
        label = convert([item(draft_caption="")], bank).labels[0]
        assert label.edits is not None and label.edits.caption_changed is True

    def test_a_prediction_with_no_result_is_passed_over_for_one_that_has_one(
        self, item, bank: VQABank
    ) -> None:  # noqa: ANN001
        raw = item()
        real = raw["predictions"][0]
        raw["predictions"] = [{"model_version": "failed-run", "result": []}, real]
        label = convert([raw], bank).labels[0]
        assert label.pseudo is not None and label.pseudo.model_version == real["model_version"]

    def test_with_no_draft_there_is_nothing_to_measure(self, item, bank: VQABank) -> None:  # noqa: ANN001
        label = convert([item(predictions=False)], bank).labels[0]
        assert label.pseudo is None and label.edits is None


class TestWhichAnnotationIsUsed:
    def annotation(self, ls_result, answers, caption, **over):  # noqa: ANN001, ANN201
        return {
            "id": 1,
            "completed_by": 1,
            "was_cancelled": False,
            "updated_at": "2026-10-05T10:00:00Z",
            "result": ls_result(caption, answers, "Yes"),
            **over,
        }

    def test_the_latest_by_update_time_wins(
        self, item, bank, ls_result, answers_for, questions
    ) -> None:  # noqa: ANN001
        base = answers_for(questions)
        old = self.annotation(
            ls_result, base, "Old caption.", id=99, updated_at="2026-10-05T09:00:00Z"
        )
        new = self.annotation(
            ls_result, base, "New caption.", id=2, updated_at="2026-10-05T11:00:00Z"
        )
        assert convert([item(annotations=[old, new])], bank).labels[0].caption == "New caption."
        assert convert([item(annotations=[new, old])], bank).labels[0].caption == "New caption."

    def test_the_higher_id_breaks_a_tie_in_time(
        self, item, bank, ls_result, answers_for, questions
    ) -> None:  # noqa: ANN001
        base = answers_for(questions)
        a = self.annotation(ls_result, base, "First.", id=1)
        b = self.annotation(ls_result, base, "Second.", id=2)
        assert convert([item(annotations=[b, a])], bank).labels[0].caption == "Second."

    def test_a_cancelled_annotation_is_ignored_in_favour_of_an_earlier_finished_one(  # noqa: ANN201
        self,
        item,
        bank,
        ls_result,
        answers_for,
        questions,  # noqa: ANN001
    ):
        base = answers_for(questions)
        done = self.annotation(
            ls_result, base, "Finished.", id=1, updated_at="2026-10-05T09:00:00Z"
        )
        cancelled = self.annotation(
            ls_result, base, "Skipped.", id=2, updated_at="2026-10-05T11:00:00Z", was_cancelled=True
        )
        assert convert([item(annotations=[done, cancelled])], bank).labels[0].caption == "Finished."

    @pytest.mark.parametrize(
        ("by", "expected"),
        [
            ({"id": 7, "email": "p@example.com"}, "p@example.com"),
            ({"id": 7}, "7"),
            (7, "7"),
            (None, None),
        ],
    )
    def test_names_the_annotator_by_email_then_id(
        self, item, bank, ls_result, answers_for, questions, by, expected
    ) -> None:  # noqa: ANN001
        annotation = self.annotation(ls_result, answers_for(questions), "Caption.", completed_by=by)
        assert convert([item(annotations=[annotation])], bank).labels[0].annotator == expected


class TestSkipping:
    def skipped(self, bank, raw):  # noqa: ANN001, ANN201
        converted = convert([raw], bank)
        assert converted.labels == []
        return {reason: keys for reason, keys in converted.skipped.items() if keys}

    def test_a_task_nobody_labelled(self, item, bank: VQABank) -> None:  # noqa: ANN001
        assert self.skipped(bank, item(annotations=[])) == {
            "no_annotation": ["clip-1|cam02|precursor"]
        }

    def test_a_task_that_was_only_cancelled_or_left_empty(self, item, bank: VQABank) -> None:  # noqa: ANN001
        cancelled = {"id": 1, "was_cancelled": True, "result": [{"from_name": "caption"}]}
        empty = {"id": 2, "was_cancelled": False, "result": []}
        assert list(self.skipped(bank, item(annotations=[cancelled]))) == ["cancelled"]
        assert list(self.skipped(bank, item(annotations=[empty]))) == ["cancelled"]

    def test_an_unusable_clip_is_dropped_even_if_everything_else_is_filled_in(
        self, item, bank: VQABank
    ) -> None:  # noqa: ANN001
        assert list(self.skipped(bank, item(usable="No"))) == ["unusable"]

    def test_a_task_that_was_never_marked_usable_counts_as_usable(
        self, item, bank: VQABank
    ) -> None:  # noqa: ANN001
        assert len(convert([item(usable=None)], bank).labels) == 1

    @pytest.mark.parametrize("caption", [None, "", "   "])
    def test_no_caption(self, item, bank: VQABank, caption: str | None) -> None:  # noqa: ANN001
        assert list(self.skipped(bank, item(caption=caption))) == ["no_caption"]

    def test_an_unanswered_question_makes_it_incomplete(
        self, item, bank: VQABank, questions
    ) -> None:  # noqa: ANN001
        raw = item()
        raw["annotations"][0]["result"] = [
            r for r in raw["annotations"][0]["result"] if r["from_name"] != questions[0].id
        ]
        assert list(self.skipped(bank, raw)) == ["incomplete"]

    def test_an_answer_the_question_does_not_offer_makes_it_incomplete(
        self, item, bank: VQABank, questions
    ) -> None:  # noqa: ANN001
        assert list(self.skipped(bank, item(answers={questions[0].id: "Maybe"}))) == ["incomplete"]

    def test_cannot_tell_is_a_complete_answer(self, item, bank: VQABank, questions) -> None:  # noqa: ANN001
        converted = convert([item(answers={q.id: CANNOT_TELL for q in questions})], bank)
        assert len(converted.labels) == 1
        assert {v.a for v in converted.labels[0].vqa} == {CANNOT_TELL}

    def test_every_skip_has_a_known_reason_and_they_are_all_counted_in_the_total(
        self, item, bank: VQABank
    ) -> None:  # noqa: ANN001
        converted = convert(
            [item(), item(annotations=[]), item(usable="No"), item(caption=None)], bank
        )
        assert set(converted.skipped) <= set(SKIP_REASONS)
        assert converted.tasks == 4 and len(converted.labels) == 1


class TestEventTypes:
    def test_an_event_type_with_its_own_questions_uses_them(
        self, item, bank, make_task, ls_result
    ) -> None:  # noqa: ANN001
        questions = bank.questions_for("running")
        answers = {q.id: q.answers[0] for q in questions}
        raw = item(task_over={"event_type": "running"}, answers=answers, draft_answers=answers)
        raw["annotations"][0]["result"] = ls_result(DRAFT_CAPTION, answers, "Yes")
        raw["predictions"][0]["result"] = ls_result(DRAFT_CAPTION, answers)
        label = convert([raw], bank).labels[0]
        assert [v.id for v in label.vqa] == [q.id for q in questions]

    def test_an_event_type_the_bank_does_not_know_uses_the_default_questions(
        self, item, bank, ls_result
    ) -> None:  # noqa: ANN001
        questions = bank.questions_for("default")
        answers = {q.id: q.answers[0] for q in questions}
        raw = item(task_over={"event_type": "tailgating"})
        raw["annotations"][0]["result"] = ls_result(DRAFT_CAPTION, answers, "Yes")
        raw["predictions"] = []
        label = convert([raw], bank).labels[0]
        assert [v.id for v in label.vqa] == [q.id for q in questions]


class TestFiles:
    def test_round_trips_through_jsonl(self, item, bank, tmp_path: Path) -> None:  # noqa: ANN001
        labels = convert([item(), item(caption="Something else.")], bank).labels
        path = tmp_path / "phavr_labels.jsonl"
        assert write_jsonl(labels, path) == 2
        again = [PhavrLabel.model_validate_json(line) for line in path.read_text().splitlines()]
        assert again == labels

    def test_reads_an_export_and_refuses_anything_that_is_not_a_list(self, tmp_path: Path) -> None:
        good = tmp_path / "export.json"
        good.write_text(json.dumps([{"data": {}}]))
        assert read_export(good) == [{"data": {}}]
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"tasks": []}))
        with pytest.raises(ValueError, match="a JSON list of tasks"):
            read_export(bad)

    def test_a_task_whose_data_is_not_ours_is_an_error_not_a_silent_skip(
        self, bank: VQABank
    ) -> None:
        with pytest.raises(ValueError):
            convert([{"data": {"clip_id": "x"}, "annotations": []}], bank)
