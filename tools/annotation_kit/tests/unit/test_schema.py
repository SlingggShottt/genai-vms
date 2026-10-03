from __future__ import annotations

import json
from pathlib import Path

import pytest
from annotation_kit.phases import PHASE_DEFINITIONS, PHASES
from annotation_kit.schema import PhaseLabelClip, PhaseSpan
from pydantic import ValidationError


def test_the_five_phases_each_have_a_definition_in_order() -> None:
    assert PHASES == ("baseline", "precursor", "escalation", "action", "aftermath")
    assert tuple(PHASE_DEFINITIONS) == PHASES
    assert all(PHASE_DEFINITIONS[p].endswith(".") for p in PHASES)


def test_the_proposed_phase_export_example_is_valid(repo: Path) -> None:
    clip = PhaseLabelClip.model_validate(
        json.loads((repo / "ml/annotation/phase_export_example.json").read_text())
    )
    assert clip.primary_view == "cam02"
    assert [p.phase for p in clip.phases] == ["baseline", "precursor", "escalation", "action"]
    assert len(clip.views) == 2


class TestPhaseSpan:
    def test_must_end_after_it_starts(self) -> None:
        with pytest.raises(ValidationError, match="must be after start_s"):
            PhaseSpan(phase="action", start_s=5, end_s=5)
        with pytest.raises(ValidationError, match="must be after start_s"):
            PhaseSpan(phase="action", start_s=5, end_s=4)

    def test_may_not_start_before_zero_or_be_an_unknown_phase(self) -> None:
        with pytest.raises(ValidationError):
            PhaseSpan(phase="action", start_s=-1, end_s=4)
        with pytest.raises(ValidationError):
            PhaseSpan.model_validate({"phase": "climax", "start_s": 0, "end_s": 1})


class TestPhaseLabelClip:
    def test_a_valid_clip(self, make_clip) -> None:  # noqa: ANN001
        assert make_clip().clip_id == "clip-1"

    def test_the_primary_view_must_be_one_of_the_views(self, make_clip) -> None:  # noqa: ANN001
        with pytest.raises(ValidationError, match="primary_view 'cam09'"):
            make_clip(primary_view="cam09")

    def test_a_camera_may_appear_once(self, make_clip) -> None:  # noqa: ANN001
        views = [{"camera": "cam02", "video_uri": "a"}, {"camera": "cam02", "video_uri": "b"}]
        with pytest.raises(ValidationError, match="appears twice"):
            make_clip(views=views)

    def test_phases_must_be_in_the_canonical_order(self, make_clip) -> None:  # noqa: ANN001
        phases = [
            {"phase": "precursor", "start_s": 0, "end_s": 3},
            {"phase": "baseline", "start_s": 3, "end_s": 6},
        ]
        with pytest.raises(ValidationError, match="in order"):
            make_clip(phases=phases)

    def test_a_phase_may_appear_once(self, make_clip) -> None:  # noqa: ANN001
        phases = [
            {"phase": "baseline", "start_s": 0, "end_s": 3},
            {"phase": "baseline", "start_s": 3, "end_s": 6},
        ]
        with pytest.raises(ValidationError, match="at most once"):
            make_clip(phases=phases)

    def test_phases_may_not_overlap(self, make_clip) -> None:  # noqa: ANN001
        phases = [
            {"phase": "baseline", "start_s": 0, "end_s": 4},
            {"phase": "precursor", "start_s": 3, "end_s": 6},
        ]
        with pytest.raises(ValidationError, match="starts before baseline ends"):
            make_clip(phases=phases)

    def test_a_phase_with_nothing_in_it_is_just_left_out(self, make_clip) -> None:  # noqa: ANN001
        phases = [
            {"phase": "baseline", "start_s": 0, "end_s": 3},
            {"phase": "action", "start_s": 3, "end_s": 6},
        ]
        assert [p.phase for p in make_clip(phases=phases).phases] == ["baseline", "action"]

    def test_phases_may_touch(self, make_clip) -> None:  # noqa: ANN001
        assert len(make_clip().phases) == 2  # baseline ends at 3.5, precursor starts at 3.5

    def test_needs_a_view_and_a_phase(self, make_clip) -> None:  # noqa: ANN001
        with pytest.raises(ValidationError):
            make_clip(views=[])
        with pytest.raises(ValidationError):
            make_clip(phases=[])

    def test_refuses_fields_it_does_not_know(self, make_clip) -> None:  # noqa: ANN001
        with pytest.raises(ValidationError):
            make_clip(mood="tense")


def test_a_tasks_key_is_stable_and_identifies_clip_view_and_phase(make_task) -> None:  # noqa: ANN001
    assert make_task().key == "clip-1|cam02|precursor"
    assert make_task(view="cam04").key != make_task().key
    assert make_task(phase="action").key != make_task().key


class TestPhavrLabel:
    def _fields(self, **over):  # noqa: ANN003, ANN202
        fields = {
            "clip_id": "c",
            "source_video": "s",
            "event_type": "intrusion",
            "view": "cam02",
            "phase": "action",
            "start_s": 0,
            "end_s": 1,
            "caption": "A caption.",
            "vqa": [],
            "pseudo": None,
            "edits": None,
            "annotator": None,
        }
        fields.update(over)
        return fields

    def test_a_label_with_no_draft_is_fine(self) -> None:
        from annotation_kit.schema import PhavrLabel

        assert PhavrLabel(**self._fields()).pseudo is None

    def test_a_label_with_a_draft_and_its_edits_is_fine(self) -> None:
        from annotation_kit.schema import Edits, PhavrLabel, PseudoLabel

        label = PhavrLabel(
            **self._fields(
                pseudo=PseudoLabel(model_version="m", caption="d", vqa={}),
                edits=Edits(caption_changed=False, caption_similarity=1.0, answers_changed=[]),
            )
        )
        assert label.edits is not None

    def test_a_draft_without_edits_or_edits_without_a_draft_is_refused(self) -> None:
        from annotation_kit.schema import Edits, PhavrLabel, PseudoLabel

        draft = PseudoLabel(model_version="m", caption="d", vqa={})
        edits = Edits(caption_changed=False, caption_similarity=1.0, answers_changed=[])
        with pytest.raises(ValidationError, match="both be present, or both absent"):
            PhavrLabel(**self._fields(pseudo=draft))
        with pytest.raises(ValidationError, match="both be present, or both absent"):
            PhavrLabel(**self._fields(edits=edits))

    def test_similarity_is_between_zero_and_one(self) -> None:
        from annotation_kit.schema import Edits

        for bad in (-0.1, 1.1):
            with pytest.raises(ValidationError):
                Edits(caption_changed=True, caption_similarity=bad, answers_changed=[])
