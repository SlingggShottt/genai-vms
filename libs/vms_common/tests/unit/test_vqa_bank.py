from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from vms_common.vqa_bank import (
    CANNOT_TELL,
    DEFAULT_EVENT_TYPE,
    MAX_OPTIONS,
    MAX_QUESTIONS,
    MIN_OPTIONS,
    MIN_QUESTIONS,
    VQABank,
    VQAQuestion,
    load_vqa_bank,
    parse_vqa_bank,
)

REPO = Path(__file__).resolve().parents[4]


def _yes_no(event_type: str, n: int) -> dict[str, str]:
    return {"id": f"{event_type}.q{n}", "text": f"Question {n}?", "kind": "yes_no"}


def _questions(event_type: str, count: int = MIN_QUESTIONS) -> list[dict[str, object]]:
    return [_yes_no(event_type, n) for n in range(count)]


def _bank(**event_types: list[dict[str, object]]) -> dict[str, object]:
    types = {DEFAULT_EVENT_TYPE: _questions(DEFAULT_EVENT_TYPE), **event_types}
    return {"version": 1, "event_types": types}


class TestTheCommittedBank:
    """config/vqa_bank.yaml is what annotators verify and what the adapter is scored on."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        # Per test, not at import: a bad bank then fails these tests, not the module's collection.
        self.bank = load_vqa_bank(REPO / "config/vqa_bank.yaml")

    def test_loads_and_has_a_default_set(self) -> None:
        assert DEFAULT_EVENT_TYPE in self.bank.event_types

    def test_covers_every_event_type_the_rules_can_raise(self) -> None:
        rules = yaml.safe_load((REPO / "config/rules.yaml").read_text())["rules"]
        raised = {rule_id.split(".")[0] for rule_id in rules}
        assert raised  # not vacuous
        missing = sorted(raised - set(self.bank.event_types))
        assert not missing, f"add questions for {missing} to config/vqa_bank.yaml"

    def test_every_event_type_has_five_to_eight_questions(self) -> None:
        for event_type, questions in self.bank.event_types.items():
            assert MIN_QUESTIONS <= len(questions) <= MAX_QUESTIONS, event_type

    def test_has_both_kinds_of_question(self) -> None:
        kinds = {q.kind for questions in self.bank.event_types.values() for q in questions}
        assert kinds == {"yes_no", "choice"}

    def test_intrusion_asks_what_the_design_example_asks(self) -> None:
        # design_architecture.md section 8.3: barrier, carrying, staff, direction, lighting.
        ids = {q.id for q in self.bank.questions_for("intrusion")}
        assert {
            "intrusion.crossing_barrier",
            "intrusion.carrying_item",
            "intrusion.staff_visible",
            "intrusion.direction",
            "intrusion.area_lit",
        } <= ids

    def test_every_question_offers_a_way_out(self) -> None:
        for questions in self.bank.event_types.values():
            for question in questions:
                assert question.answers[-1] == CANNOT_TELL


class TestTheLimitsAsWritten:
    """The numbers in the spec (5-8 questions, 2-6 options), not the constants that hold them."""

    @pytest.mark.parametrize("count", [5, 8])
    def test_five_and_eight_questions_are_accepted(self, count: int) -> None:
        assert (
            len(parse_vqa_bank(_bank(alpha=_questions("alpha", count))).event_types["alpha"])
            == count
        )

    @pytest.mark.parametrize("count", [4, 9])
    def test_four_and_nine_questions_are_refused(self, count: int) -> None:
        with pytest.raises(ValidationError, match="5 to 8 questions"):
            parse_vqa_bank(_bank(alpha=_questions("alpha", count)))

    @pytest.mark.parametrize("count", [2, 6])
    def test_two_and_six_options_are_accepted(self, count: int) -> None:
        options = [f"o{i}" for i in range(count)]
        assert VQAQuestion(id="x.y", text="Which?", kind="choice", options=tuple(options))

    @pytest.mark.parametrize("count", [1, 7])
    def test_one_and_seven_options_are_refused(self, count: int) -> None:
        options = tuple(f"o{i}" for i in range(count))
        with pytest.raises(ValidationError, match="2 to 6 options"):
            VQAQuestion(id="x.y", text="Which?", kind="choice", options=options)


class TestAcceptedBanks:
    def test_the_smallest_and_largest_set_are_fine(self) -> None:
        bank = parse_vqa_bank(
            _bank(
                small=_questions("small", MIN_QUESTIONS), large=_questions("large", MAX_QUESTIONS)
            )
        )
        assert len(bank.event_types["small"]) == MIN_QUESTIONS
        assert len(bank.event_types["large"]) == MAX_QUESTIONS

    @pytest.mark.parametrize("count", [MIN_OPTIONS, MAX_OPTIONS])
    def test_a_choice_may_have_two_to_six_options(self, count: int) -> None:
        question = {
            "id": "x.which",
            "text": "Which?",
            "kind": "choice",
            "options": [f"option {i}" for i in range(count)],
        }
        assert VQAQuestion.model_validate(question).options == tuple(
            f"option {i}" for i in range(count)
        )


class TestRefusedBanks:
    @pytest.mark.parametrize("count", [MIN_QUESTIONS - 1, MAX_QUESTIONS + 1, 0])
    def test_wrong_number_of_questions(self, count: int) -> None:
        with pytest.raises(ValidationError, match="questions are required"):
            parse_vqa_bank(_bank(intrusion=_questions("intrusion", count)))

    def test_no_default_set(self) -> None:
        data = _bank()
        del data["event_types"][DEFAULT_EVENT_TYPE]  # type: ignore[attr-defined]
        with pytest.raises(ValidationError, match="needs a 'default' set"):
            parse_vqa_bank(data)

    def test_an_id_used_twice(self) -> None:
        first = _questions("alpha")
        second = _questions("beta")
        second[0] = {**second[0], "id": "alpha.q0"}  # same id as alpha's, filed under beta
        with pytest.raises(ValidationError, match="but its id says 'alpha'"):
            parse_vqa_bank(_bank(alpha=first, beta=second))

    def test_the_same_id_twice_within_one_event_type(self) -> None:
        questions = _questions("alpha")
        questions[1] = dict(questions[0])
        with pytest.raises(ValidationError, match="appears twice"):
            parse_vqa_bank(_bank(alpha=questions))

    def test_an_id_that_belongs_to_another_event_type(self) -> None:
        questions = _questions("alpha")
        questions[2] = {**questions[2], "id": "beta.q2"}
        with pytest.raises(ValidationError, match="is under 'alpha' but its id says 'beta'"):
            parse_vqa_bank(_bank(alpha=questions))

    @pytest.mark.parametrize("bad", ["Alpha", "1alpha", "alpha-beta", "alpha beta"])
    def test_an_event_type_that_is_not_snake_case(self, bad: str) -> None:
        with pytest.raises(ValidationError, match="lower snake case"):
            parse_vqa_bank(_bank(**{bad: _questions(bad)}))

    def test_an_unknown_version(self) -> None:
        with pytest.raises(ValidationError):
            parse_vqa_bank({**_bank(), "version": 2})

    def test_an_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            parse_vqa_bank({**_bank(), "owner": "J"})
        questions = _questions("alpha")
        questions[0] = {**questions[0], "weight": 3}
        with pytest.raises(ValidationError):
            parse_vqa_bank(_bank(alpha=questions))


class TestRefusedQuestions:
    @pytest.mark.parametrize(
        "bad_id",
        ["crossing", "Intrusion.crossing", "intrusion.Crossing", "intrusion.", ".x", "a.b.c"],
    )
    def test_an_id_that_is_not_event_type_dot_name(self, bad_id: str) -> None:
        with pytest.raises(ValidationError, match="must look like"):
            VQAQuestion.model_validate({"id": bad_id, "text": "Ok?", "kind": "yes_no"})

    @pytest.mark.parametrize("text", ["Is it open", "Is it open.", "", "Is it open ?!"])
    def test_text_that_is_not_a_question(self, text: str) -> None:
        with pytest.raises(ValidationError):
            VQAQuestion.model_validate({"id": "x.y", "text": text, "kind": "yes_no"})

    def test_a_yes_no_with_options(self) -> None:
        with pytest.raises(ValidationError, match="has no options"):
            VQAQuestion.model_validate(
                {"id": "x.y", "text": "Ok?", "kind": "yes_no", "options": ["a", "b"]}
            )

    @pytest.mark.parametrize("count", [0, 1, MAX_OPTIONS + 1])
    def test_a_choice_with_too_few_or_too_many_options(self, count: int) -> None:
        with pytest.raises(ValidationError, match="options, got"):
            VQAQuestion.model_validate(
                {
                    "id": "x.y",
                    "text": "Which?",
                    "kind": "choice",
                    "options": [f"o{i}" for i in range(count)],
                }
            )

    def test_options_that_repeat_each_other_ignoring_case_and_spaces(self) -> None:
        with pytest.raises(ValidationError, match="different from each other"):
            VQAQuestion.model_validate(
                {"id": "x.y", "text": "Which?", "kind": "choice", "options": ["Left", " left "]}
            )

    def test_an_empty_option(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            VQAQuestion.model_validate(
                {"id": "x.y", "text": "Which?", "kind": "choice", "options": ["Left", "  "]}
            )

    @pytest.mark.parametrize("option", [CANNOT_TELL, CANNOT_TELL.upper(), " cannot tell "])
    def test_an_option_that_is_already_always_allowed(self, option: str) -> None:
        with pytest.raises(ValidationError, match="always allowed"):
            VQAQuestion.model_validate(
                {"id": "x.y", "text": "Which?", "kind": "choice", "options": ["Left", option]}
            )


class TestUsingABank:
    def _question(self, kind: str = "yes_no", options: tuple[str, ...] = ()) -> VQAQuestion:
        return VQAQuestion(id="x.y", text="Ok?", kind=kind, options=options)  # type: ignore[arg-type]

    def test_a_yes_no_accepts_yes_no_and_cannot_tell(self) -> None:
        assert self._question().answers == ("Yes", "No", CANNOT_TELL)

    def test_a_choice_accepts_its_options_then_cannot_tell(self) -> None:
        assert self._question("choice", ("Left", "Right")).answers == ("Left", "Right", CANNOT_TELL)

    def test_questions_for_a_known_type_are_its_own(self) -> None:
        bank = parse_vqa_bank(_bank(alpha=_questions("alpha")))
        assert [q.id for q in bank.questions_for("alpha")] == [f"alpha.q{n}" for n in range(5)]

    def test_questions_for_an_unknown_type_are_the_default_set(self) -> None:
        bank = parse_vqa_bank(_bank(alpha=_questions("alpha")))
        assert bank.questions_for("never_heard_of_it") == bank.event_types[DEFAULT_EVENT_TYPE]

    def test_a_question_is_found_by_id_wherever_it_is(self) -> None:
        bank = parse_vqa_bank(_bank(alpha=_questions("alpha"), beta=_questions("beta")))
        assert bank.question("beta.q3").text == "Question 3?"
        assert bank.question("default.q0").id == "default.q0"

    def test_an_unknown_question_id(self) -> None:
        bank = parse_vqa_bank(_bank())
        with pytest.raises(KeyError):
            bank.question("alpha.nope")

    def test_a_bank_cannot_be_changed(self) -> None:
        bank = parse_vqa_bank(_bank())
        with pytest.raises(ValidationError):
            bank.version = 2  # type: ignore[misc]
        with pytest.raises(ValidationError):
            bank.event_types[DEFAULT_EVENT_TYPE][0].text = "Changed?"  # type: ignore[misc]


class TestLoading:
    def test_loads_a_file(self, tmp_path: Path) -> None:
        path = tmp_path / "bank.yaml"
        path.write_text(yaml.safe_dump(_bank(alpha=_questions("alpha"))))
        assert isinstance(load_vqa_bank(path), VQABank)

    def test_accepts_a_string_path(self, tmp_path: Path) -> None:
        path = tmp_path / "bank.yaml"
        path.write_text(yaml.safe_dump(_bank()))
        assert load_vqa_bank(str(path)).version == 1

    @pytest.mark.parametrize("content", ["- just\n- a list\n", "42\n", ""])
    def test_a_file_that_is_not_a_mapping(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / "bank.yaml"
        path.write_text(content)
        with pytest.raises(ValueError, match="expected a mapping"):
            load_vqa_bank(path)

    def test_a_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_vqa_bank(tmp_path / "nope.yaml")
