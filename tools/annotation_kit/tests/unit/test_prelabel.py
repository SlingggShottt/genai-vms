from __future__ import annotations

import json
import re

import pytest
from annotation_kit.labelconfig import CAPTION, VIDEO
from annotation_kit.phases import PHASE_DEFINITIONS
from annotation_kit.prelabel import (
    PROMPT_VERSION,
    Draft,
    load_prompt,
    parse_draft,
    preannotate,
    prediction_result,
    render_prompt,
    render_questions,
)
from vms_common.vqa_bank import CANNOT_TELL, VQABank, VQAQuestion

YES_NO = VQAQuestion(id="t.carrying", text="Is the person carrying anything?", kind="yes_no")
CHOICE = VQAQuestion(
    id="t.direction", text="Which way?", kind="choice", options=("Left", "Right", "Away from it")
)
QUESTIONS = (YES_NO, CHOICE)


def reply(caption: object = "A person walks along the fence.", **answers: object) -> str:
    return json.dumps(
        {"caption": caption, "answers": {"t.carrying": "Yes", "t.direction": "Left", **answers}}
    )


class TestThePrompt:
    def test_is_a_versioned_file(self) -> None:
        assert PROMPT_VERSION == "prelabel/1.0"
        assert "$questions" in load_prompt().template

    def test_says_what_the_task_is(self, make_task, bank: VQABank) -> None:  # noqa: ANN001
        prompt = render_prompt(make_task(), bank.questions_for("intrusion"))
        assert "Event type: intrusion" in prompt
        assert "Camera view: cam02" in prompt
        assert f"Phase: precursor - {PHASE_DEFINITIONS['precursor']}" in prompt
        assert "Time span: 3.5 s to 9 s" in prompt

    def test_names_the_event_type_in_words(self, make_task) -> None:  # noqa: ANN001
        prompt = render_prompt(make_task(event_type="abandoned_object"), QUESTIONS)
        assert "Event type: abandoned object" in prompt

    def test_lists_every_question_with_its_id_and_allowed_answers(self, make_task) -> None:  # noqa: ANN001
        prompt = render_prompt(make_task(), QUESTIONS)
        assert (
            f"- t.carrying: Is the person carrying anything? Answers: Yes | No | {CANNOT_TELL}"
            in prompt
        )
        assert (
            f"- t.direction: Which way? Answers: Left | Right | Away from it | {CANNOT_TELL}"
            in prompt
        )

    def test_leaves_no_placeholder_behind(self, make_task, bank: VQABank) -> None:  # noqa: ANN001
        for event_type in bank.event_types:
            prompt = render_prompt(make_task(event_type=event_type), bank.questions_for(event_type))
            assert not re.search(r"\$[a-z_]+", prompt), event_type

    def test_asks_for_json_and_for_honesty_about_what_cannot_be_seen(self, make_task) -> None:  # noqa: ANN001
        prompt = render_prompt(make_task(), QUESTIONS)
        assert "Reply with JSON only" in prompt
        assert '"caption"' in prompt and '"answers"' in prompt
        assert 'answer "Cannot tell" rather than guessing' in prompt

    def test_one_line_per_question(self) -> None:
        assert len(render_questions(QUESTIONS).splitlines()) == 2


class TestReadingAReply:
    def test_a_clean_reply(self) -> None:
        draft = parse_draft(reply(), QUESTIONS)
        assert draft == Draft(
            caption="A person walks along the fence.",
            answers={"t.carrying": "Yes", "t.direction": "Left"},
        )

    def test_json_inside_a_code_fence_and_chatter(self) -> None:
        raw = f"Sure! Here is the label:\n```json\n{reply()}\n```\nHope that helps."
        assert parse_draft(raw, QUESTIONS).answers == {"t.carrying": "Yes", "t.direction": "Left"}

    def test_braces_inside_the_caption_do_not_confuse_it(self) -> None:
        draft = parse_draft(reply(caption="A sign reads {EXIT} near the gate."), QUESTIONS)
        assert draft.caption == "A sign reads {EXIT} near the gate."
        assert draft.problems == ()

    def test_skips_a_stray_brace_before_the_object(self) -> None:
        assert parse_draft("{ not json } then " + reply(), QUESTIONS).caption.startswith("A person")

    def test_answers_are_matched_ignoring_case_quotes_and_a_trailing_full_stop(self) -> None:
        draft = parse_draft(
            reply(**{"t.carrying": "yes.", "t.direction": '"away from it"'}), QUESTIONS
        )
        assert draft.answers == {"t.carrying": "Yes", "t.direction": "Away from it"}
        assert draft.problems == ()

    def test_a_json_boolean_is_a_yes_or_no(self) -> None:
        assert parse_draft(reply(**{"t.carrying": True}), QUESTIONS).answers["t.carrying"] == "Yes"
        assert parse_draft(reply(**{"t.carrying": False}), QUESTIONS).answers["t.carrying"] == "No"

    def test_a_boolean_is_not_a_choice(self) -> None:
        draft = parse_draft(reply(**{"t.direction": True}), QUESTIONS)
        assert draft.answers["t.direction"] == CANNOT_TELL
        assert draft.coerced == ("t.direction",)

    def test_cannot_tell_from_the_model_is_not_a_problem(self) -> None:
        draft = parse_draft(reply(**{"t.carrying": "Cannot tell"}), QUESTIONS)
        assert draft.answers["t.carrying"] == CANNOT_TELL
        assert draft.coerced == () and draft.problems == ()

    def test_an_answer_that_is_not_allowed_becomes_cannot_tell_and_is_counted(self) -> None:
        draft = parse_draft(reply(**{"t.direction": "Up"}), QUESTIONS)
        assert draft.answers["t.direction"] == CANNOT_TELL
        assert draft.coerced == ("t.direction",)
        assert any("'Up' is not an allowed answer" in p for p in draft.problems)

    @pytest.mark.parametrize("bad", [None, 3, ["Yes"], {"a": 1}])
    def test_an_answer_of_the_wrong_type_becomes_cannot_tell(self, bad: object) -> None:
        assert (
            parse_draft(reply(**{"t.carrying": bad}), QUESTIONS).answers["t.carrying"]
            == CANNOT_TELL
        )

    def test_a_missing_answer_becomes_cannot_tell_and_is_counted(self) -> None:
        raw = json.dumps({"caption": "A person.", "answers": {"t.carrying": "No"}})
        draft = parse_draft(raw, QUESTIONS)
        assert draft.answers == {"t.carrying": "No", "t.direction": CANNOT_TELL}
        assert draft.coerced == ("t.direction",)

    def test_every_question_always_has_an_answer(self) -> None:
        for raw in [reply(), "nonsense", "{}", '{"caption": 5, "answers": 7}']:
            assert set(parse_draft(raw, QUESTIONS).answers) == {"t.carrying", "t.direction"}

    def test_a_missing_or_wrong_caption_is_a_problem_but_the_answers_survive(self) -> None:
        for caption in [None, 5, "", "   "]:
            draft = parse_draft(reply(caption=caption), QUESTIONS)
            assert draft.caption == ""
            assert "no caption" in draft.problems
            assert draft.answers["t.carrying"] == "Yes"
            assert not draft.unparseable

    def test_answers_that_are_not_an_object(self) -> None:
        draft = parse_draft(
            json.dumps({"caption": "A person.", "answers": ["Yes", "Left"]}), QUESTIONS
        )
        assert "no answers object" in draft.problems
        assert draft.coerced == ("t.carrying", "t.direction")

    def test_the_caption_is_tidied_onto_one_line(self) -> None:
        assert (
            parse_draft(reply(caption="  A person\n  walks   by.  "), QUESTIONS).caption
            == "A person walks by."
        )

    def test_answers_to_questions_nobody_asked_are_ignored(self) -> None:
        draft = parse_draft(reply(**{"t.invented": "Yes"}), QUESTIONS)
        assert set(draft.answers) == {"t.carrying", "t.direction"}
        assert draft.problems == ()

    @pytest.mark.parametrize(
        "raw", ["", "I cannot help with that.", "[1, 2]", "{broken", "```json\n```"]
    )
    def test_a_reply_with_no_json_object_is_unparseable_and_all_cannot_tell(self, raw: str) -> None:
        draft = parse_draft(raw, QUESTIONS)
        assert draft.unparseable
        assert draft.caption == ""
        assert draft.answers == {"t.carrying": CANNOT_TELL, "t.direction": CANNOT_TELL}
        assert draft.coerced == ("t.carrying", "t.direction")


class TestThePrediction:
    def test_names_the_controls_of_the_generated_config(self) -> None:
        result = prediction_result(parse_draft(reply(), QUESTIONS), QUESTIONS)
        assert result[0] == {
            "from_name": CAPTION,
            "to_name": VIDEO,
            "type": "textarea",
            "value": {"text": ["A person walks along the fence."]},
        }
        assert result[1:] == [
            {
                "from_name": "t.carrying",
                "to_name": VIDEO,
                "type": "choices",
                "value": {"choices": ["Yes"]},
            },
            {
                "from_name": "t.direction",
                "to_name": VIDEO,
                "type": "choices",
                "value": {"choices": ["Left"]},
            },
        ]

    def test_leaves_the_caption_out_when_there_is_none(self) -> None:
        result = prediction_result(parse_draft(reply(caption=""), QUESTIONS), QUESTIONS)
        assert [r["from_name"] for r in result] == ["t.carrying", "t.direction"]


class TestPreannotating:
    def labeler(self, replies: list[str]):  # noqa: ANN202
        calls: list[tuple[str, str]] = []
        queue = iter(replies)

        def run(task, prompt):  # noqa: ANN001, ANN202
            calls.append((task.key, prompt))
            return next(queue)

        run.calls = calls  # type: ignore[attr-defined]
        return run

    def test_gives_every_task_its_data_and_a_prediction(self, make_task, bank: VQABank) -> None:  # noqa: ANN001
        questions = bank.questions_for("intrusion")
        raw = json.dumps(
            {"caption": "A person walks.", "answers": {q.id: q.answers[0] for q in questions}}
        )
        items, stats = preannotate([make_task()], bank, self.labeler([raw]), model_version="m@1")
        assert items[0]["data"] == make_task().model_dump()
        prediction = items[0]["predictions"][0]
        assert prediction["model_version"] == "m@1"
        assert len(prediction["result"]) == 1 + len(questions)
        assert (stats.tasks, stats.unparseable, stats.coerced_answers) == (1, 0, 0)

    def test_the_model_is_given_the_prompt_for_that_task(self, make_task, bank: VQABank) -> None:  # noqa: ANN001
        run = self.labeler(["{}", "{}"])
        preannotate([make_task(), make_task(view="cam04")], bank, run, model_version="m")
        assert [key for key, _ in run.calls] == ["clip-1|cam02|precursor", "clip-1|cam04|precursor"]
        assert "Camera view: cam04" in run.calls[1][1]

    def test_an_unparseable_reply_gives_a_task_with_no_prediction_so_the_annotator_starts_blank(
        self,
        make_task,
        bank: VQABank,  # noqa: ANN001
    ) -> None:
        items, stats = preannotate(
            [make_task()], bank, self.labeler(["sorry, no"]), model_version="m"
        )
        assert items[0]["predictions"] == []
        assert stats.unparseable == 1
        assert stats.coerced_answers == len(bank.questions_for("intrusion"))

    def test_counts_what_had_to_be_coerced_over_all_answers(self, make_task, bank: VQABank) -> None:  # noqa: ANN001
        questions = bank.questions_for("intrusion")
        answers = {q.id: q.answers[0] for q in questions}
        answers[questions[0].id] = "Banana"
        raw = json.dumps({"caption": "", "answers": answers})
        _, stats = preannotate([make_task()], bank, self.labeler([raw]), model_version="m")
        assert stats.coerced_answers == 1
        assert stats.answers == len(questions)
        assert stats.without_caption == 1
        assert stats.coerced_rate == pytest.approx(1 / len(questions))

    def test_an_event_type_the_bank_does_not_know_is_asked_the_default_questions(
        self,
        make_task,
        bank: VQABank,  # noqa: ANN001
    ) -> None:
        run = self.labeler(["{}"])
        items, stats = preannotate(
            [make_task(event_type="tailgating")], bank, run, model_version="m"
        )
        assert "default.people_visible" in run.calls[0][1]
        assert stats.answers == len(bank.questions_for("default"))
        assert (
            items[0]["predictions"][0]["result"][-1]["from_name"]
            == bank.questions_for("default")[-1].id
        )

    def test_no_tasks_is_fine(self, bank: VQABank) -> None:
        items, stats = preannotate([], bank, self.labeler([]), model_version="m")
        assert items == [] and stats.tasks == 0 and stats.coerced_rate == 0.0
