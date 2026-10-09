from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from annotation_kit.candidates import FPS
from annotation_kit.phaseconfig import (
    EVENT_TYPE,
    FRAMERATE,
    MAX_VIEWS,
    PHASE,
    PRIMARY_VIEW,
    build_phase_config,
    config_filename,
    video_name,
    write_phase_configs,
)
from annotation_kit.phases import PHASE_DEFINITIONS, PHASES

TYPES = ["intrusion", "theft", "activity"]


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)  # noqa: S314 - the config this module generated


def test_phases_are_marked_at_a_rate_coarse_enough_for_a_clip_to_fit_a_laptop_screen() -> None:
    """Label Studio draws a frame 16 px wide and cannot zoom the timeline out; a 1366 px laptop
    shows about 620 px of it. A 40 s clip must fit without scrolling (drawing on a scrolled
    timeline was unreliable), and a one-second grid is as coarse as it is worth going."""
    assert FRAMERATE < FPS
    assert 40 * FRAMERATE * 16 <= 650
    assert FRAMERATE >= 1


def test_video_names_are_video_then_video_2_and_so_on() -> None:
    assert [video_name(i) for i in range(4)] == ["video", "video_2", "video_3", "video_4"]


class TestVideos:
    @pytest.mark.parametrize("views", range(1, MAX_VIEWS + 1))
    def test_one_video_per_view_named_in_order(self, views: int) -> None:
        videos = parse(build_phase_config(TYPES, views)).findall("Video")
        assert [v.attrib["name"] for v in videos] == [video_name(i) for i in range(views)]
        assert [v.attrib["value"] for v in videos] == [f"${video_name(i)}" for i in range(views)]
        assert all(v.attrib["framerate"] == str(FRAMERATE) for v in videos)

    def test_only_the_first_has_a_timeline_to_mark(self) -> None:
        videos = parse(build_phase_config(TYPES, 3)).findall("Video")
        assert int(videos[0].attrib["timelineHeight"]) >= 30 + 24 * len(
            PHASES
        )  # no phase row cut off
        assert all("timelineHeight" not in v.attrib for v in videos[1:])

    def test_several_views_say_the_others_are_for_looking(self) -> None:
        text = [h.attrib["value"] for h in parse(build_phase_config(TYPES, 2)).iter("Header")]
        assert any("same moment from other cameras" in t for t in text)
        text1 = [h.attrib["value"] for h in parse(build_phase_config(TYPES, 1)).iter("Header")]
        assert not any("other cameras" in t for t in text1)

    @pytest.mark.parametrize("views", [0, MAX_VIEWS + 1, -1])
    def test_refuses_a_number_of_views_it_cannot_show(self, views: int) -> None:
        with pytest.raises(ValueError, match="views must be 1 to 4"):
            build_phase_config(TYPES, views)


class TestPhases:
    def labels(self):  # noqa: ANN202
        return parse(build_phase_config(TYPES)).find("TimelineLabels")

    def test_a_timeline_attached_to_the_first_video(self) -> None:
        timeline = self.labels()
        assert timeline is not None
        assert (timeline.attrib["name"], timeline.attrib["toName"]) == (PHASE, "video")

    def test_the_five_phases_in_order_named_exactly_as_the_taxonomy(self) -> None:
        timeline = self.labels()
        assert [label.attrib["value"] for label in timeline.findall("Label")] == list(PHASES)

    def test_each_phase_has_its_own_hotkey_and_colour_and_shows_its_definition_on_hover(
        self,
    ) -> None:
        labels = self.labels().findall("Label")
        assert [label.attrib["hotkey"] for label in labels] == ["1", "2", "3", "4", "5"]
        assert len({label.attrib["background"] for label in labels}) == 5
        assert [label.attrib["hint"] for label in labels] == [PHASE_DEFINITIONS[p] for p in PHASES]

    def test_no_label_has_an_alias_because_an_alias_replaces_the_stored_value(self) -> None:
        # Found with Label Studio's own parser: with an alias the exported result holds the alias,
        # not the phase name, and the converter would not recognise any phase.
        assert all("alias" not in label.attrib for label in self.labels().findall("Label"))

    def test_there_is_no_label_for_nothing_so_a_phase_may_be_empty(self) -> None:
        values = {label.attrib["value"] for label in self.labels().findall("Label")}
        assert values == set(PHASES)


class TestTheOtherQuestions:
    def test_the_primary_view_is_chosen_from_the_tasks_own_views(self) -> None:
        choices = next(
            c
            for c in parse(build_phase_config(TYPES)).iter("Choices")
            if c.attrib["name"] == PRIMARY_VIEW
        )
        assert choices.attrib["value"] == "$view_choices" and choices.attrib["required"] == "true"
        assert choices.findall("Choice") == []  # the options come from the task

    def test_the_event_type_is_one_of_the_given_in_the_given_order(self) -> None:
        choices = next(
            c
            for c in parse(build_phase_config(TYPES)).iter("Choices")
            if c.attrib["name"] == EVENT_TYPE
        )
        assert [c.attrib["value"] for c in choices.findall("Choice")] == TYPES
        assert choices.attrib["required"] == "true"

    def test_it_asks_whether_the_clip_is_usable_last(self) -> None:
        root = parse(build_phase_config(TYPES))
        last = [c for c in root if c.tag == "Choices"][-1]
        assert last.attrib["name"] == "usable"
        assert [c.attrib["value"] for c in last.findall("Choice")] == ["Yes", "No"]

    def test_the_title_names_the_event_type_and_the_candidate(self) -> None:
        assert (
            parse(build_phase_config(TYPES)).find("Header").attrib["value"]
            == "$event_type: $candidate_id"
        )  # type: ignore[union-attr]

    def test_every_control_is_attached_to_the_first_video(self) -> None:
        root = parse(build_phase_config(TYPES, 3))
        assert {c.attrib["toName"] for c in root if c.tag in ("TimelineLabels", "Choices")} == {
            "video"
        }


class TestEventTypes:
    @pytest.mark.parametrize("bad", [[], ["a", "a"]])
    def test_refuses_none_or_repeats(self, bad: list[str]) -> None:
        with pytest.raises(ValueError, match="non-empty list without repeats"):
            build_phase_config(bad)


class TestFiles:
    def test_one_config_per_number_of_views(self, tmp_path: Path) -> None:
        paths = write_phase_configs(TYPES, tmp_path / "out")
        assert [p.name for p in paths] == [config_filename(n) for n in range(1, 5)]
        assert [p.name for p in paths] == [
            "phase_labelling_1view.xml",
            "phase_labelling_2views.xml",
            "phase_labelling_3views.xml",
            "phase_labelling_4views.xml",
        ]

    def test_is_deterministic(self) -> None:
        assert build_phase_config(TYPES, 2) == build_phase_config(TYPES, 2)
