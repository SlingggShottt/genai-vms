from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from annotation_kit.labelconfig import (
    CAPTION,
    CAPTION_HELP,
    USABLE,
    VIDEO,
    build_label_config,
    write_label_configs,
)
from vms_common.vqa_bank import CANNOT_TELL, VQABank, VQAQuestion


def _parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)  # noqa: S314 - the config this module generated, not untrusted input


def _choices(root: ET.Element) -> dict[str, list[str]]:
    return {
        c.attrib["name"]: [choice.attrib["value"] for choice in c.findall("Choice")]
        for c in root.iter("Choices")
    }


@pytest.fixture
def questions(bank: VQABank) -> tuple[VQAQuestion, ...]:
    return bank.questions_for("intrusion")


def test_is_well_formed_xml_with_a_view_root(questions) -> None:  # noqa: ANN001
    root = _parse(build_label_config("intrusion", questions))
    assert root.tag == "View"


def test_shows_the_clip_playing_just_the_phase(questions) -> None:  # noqa: ANN001
    video = _parse(build_label_config("intrusion", questions)).find("Video")
    assert video is not None
    assert (video.attrib["name"], video.attrib["value"]) == (VIDEO, "$video")


def test_the_video_is_the_only_data_object(questions) -> None:  # noqa: ANN001
    """A Text tag is a data object to Label Studio even with a fixed value; use a Header."""
    root = _parse(build_label_config("intrusion", questions))
    assert [
        element.tag for element in root.iter() if element.tag in {"Text", "Image", "Audio"}
    ] == []
    assert len(list(root.iter("Video"))) == 1


def test_tells_the_annotator_how_to_write_a_caption(questions) -> None:  # noqa: ANN001
    headers = [
        h.attrib["value"] for h in _parse(build_label_config("intrusion", questions)).iter("Header")
    ]
    assert CAPTION_HELP in headers


def test_has_a_required_caption_box_attached_to_the_video(questions) -> None:  # noqa: ANN001
    boxes = _parse(build_label_config("intrusion", questions)).findall("TextArea")
    assert len(boxes) == 1
    assert boxes[0].attrib["name"] == CAPTION
    assert boxes[0].attrib["toName"] == VIDEO
    assert boxes[0].attrib["required"] == "true"


def test_has_one_required_single_choice_per_question_named_by_its_id(questions) -> None:  # noqa: ANN001
    root = _parse(build_label_config("intrusion", questions))
    choices = _choices(root)
    assert [c for c in choices if c != USABLE] == [q.id for q in questions]
    for element in root.iter("Choices"):
        assert element.attrib["toName"] == VIDEO
        assert element.attrib["required"] == "true"
        assert element.attrib["choice"] == "single"


def test_each_question_offers_exactly_its_answers_ending_in_cannot_tell(questions) -> None:  # noqa: ANN001
    choices = _choices(_parse(build_label_config("intrusion", questions)))
    for question in questions:
        assert choices[question.id] == list(question.answers)
        assert choices[question.id][-1] == CANNOT_TELL


def test_each_question_is_asked_in_words_just_above_its_choices(questions) -> None:  # noqa: ANN001
    root = _parse(build_label_config("intrusion", questions))
    children = list(root)
    for question in questions:
        position = next(i for i, c in enumerate(children) if c.attrib.get("name") == question.id)
        assert children[position - 1].tag == "Header"
        assert children[position - 1].attrib["value"] == question.text


def test_asks_whether_the_clip_is_usable_last(questions) -> None:  # noqa: ANN001
    root = _parse(build_label_config("intrusion", questions))
    last = list(root)[-1]
    assert last.attrib["name"] == USABLE
    assert [c.attrib["value"] for c in last.findall("Choice")] == ["Yes", "No"]


def test_the_title_names_the_event_type_and_uses_the_tasks_phase_and_view(questions) -> None:  # noqa: ANN001
    header = _parse(build_label_config("abandoned_object", questions)).find("Header")
    assert header is not None
    assert header.attrib["value"] == "Abandoned object: $phase phase, view $view"


def test_text_with_markup_characters_is_escaped_not_injected() -> None:
    nasty = VQAQuestion(
        id="x.nasty", text='Is A & B <ok> "fine"?', kind="choice", options=("a<b", 'say "hi"')
    )
    xml = build_label_config("x", [nasty])
    root = _parse(xml)  # would raise if the characters had broken the markup
    assert any(h.attrib["value"] == nasty.text for h in root.iter("Header"))
    assert _choices(root)["x.nasty"][:2] == ["a<b", 'say "hi"']
    assert "<ok>" not in xml


def test_is_deterministic(questions) -> None:  # noqa: ANN001
    assert build_label_config("intrusion", questions) == build_label_config("intrusion", questions)


def test_the_same_questions_for_another_event_type_differ_only_in_the_title(questions) -> None:  # noqa: ANN001
    a = build_label_config("intrusion", questions).splitlines()
    b = build_label_config("loitering", questions).splitlines()
    assert [x for x, y in zip(a, b, strict=True) if x != y] == [a[1]]


class TestWritingTheConfigs:
    def test_one_file_per_event_type_in_the_bank(self, bank: VQABank, tmp_path: Path) -> None:
        paths = write_label_configs(bank, tmp_path / "out")
        assert sorted(p.name for p in paths) == sorted(f"{t}.xml" for t in bank.event_types)

    def test_every_written_config_matches_its_event_types_questions(
        self, bank: VQABank, tmp_path: Path
    ) -> None:
        for path in write_label_configs(bank, tmp_path):
            event_type = path.stem
            choices = _choices(_parse(path.read_text()))
            assert [c for c in choices if c != USABLE] == [
                q.id for q in bank.event_types[event_type]
            ]

    def test_the_committed_configs_are_what_the_bank_generates(
        self, bank: VQABank, repo: Path, tmp_path: Path
    ) -> None:
        """After editing config/vqa_bank.yaml, run `annotation-kit label-config --out ...`."""
        committed = repo / "ml/annotation/caption_vqa"
        generated = write_label_configs(bank, tmp_path)
        assert sorted(p.name for p in committed.glob("*.xml")) == sorted(p.name for p in generated)
        for path in generated:
            assert (committed / path.name).read_text() == path.read_text(), (
                f"{path.name} is out of date: run annotation-kit label-config"
            )
