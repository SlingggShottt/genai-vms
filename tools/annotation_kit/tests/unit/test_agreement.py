from __future__ import annotations

import pytest
from annotation_kit.agreement import (
    Agreement,
    cohens_kappa,
    compare,
    frame_labels,
    interval_iou,
    render_markdown,
)
from annotation_kit.schema import PhaseLabelClip


def clip(
    clip_id: str = "c1", phases=None, primary: str = "cam02", event_type: str = "activity"
) -> PhaseLabelClip:  # noqa: ANN001
    phases = phases if phases is not None else [("baseline", 0, 10), ("action", 10, 20)]
    return PhaseLabelClip(
        clip_id=clip_id,
        source_video="s",
        event_type=event_type,
        primary_view=primary,
        views=[{"camera": "cam02", "video_uri": "u"}, {"camera": "cam04", "video_uri": "v"}],
        phases=[{"phase": p, "start_s": s, "end_s": e} for p, s, e in phases],
    )


class TestIntervalIoU:
    def test_identical_is_one_and_disjoint_is_zero(self) -> None:
        assert interval_iou((0, 10), (0, 10)) == 1.0
        assert interval_iou((0, 10), (10, 20)) == 0.0  # touching is not overlapping
        assert interval_iou((0, 10), (15, 20)) == 0.0

    def test_partial_overlap(self) -> None:
        assert interval_iou((0, 10), (5, 15)) == pytest.approx(5 / 15)
        assert interval_iou((0, 10), (2, 8)) == pytest.approx(6 / 10)  # one inside the other

    def test_a_zero_length_interval_has_no_overlap(self) -> None:
        assert interval_iou((3, 3), (3, 3)) == 0.0


class TestFrameLabels:
    def test_labels_each_tenth_of_a_second_by_the_phase_it_falls_in(self) -> None:
        labels = frame_labels(clip(phases=[("baseline", 0, 0.2), ("action", 0.3, 0.5)]), 0.6)
        assert labels == ["baseline", "baseline", "none", "action", "action", "none"]

    def test_the_end_of_a_phase_is_exclusive(self) -> None:
        labels = frame_labels(clip(phases=[("baseline", 0, 0.3)]), 0.3)
        assert labels == ["baseline"] * 3


class TestKappa:
    def test_a_worked_example(self) -> None:
        # observed 3/4; chance .5*.25 + .5*.75 = .5; kappa = (.75 - .5) / .5
        assert cohens_kappa(list("xxyy"), list("xyyy")) == pytest.approx(0.5)

    def test_perfect_agreement_is_one_and_chance_level_is_zero(self) -> None:
        assert cohens_kappa(list("xyxy"), list("xyxy")) == 1.0
        assert cohens_kappa(list("xxyy"), list("xyxy")) == pytest.approx(0.0)

    def test_total_disagreement_is_negative(self) -> None:
        assert cohens_kappa(list("xy"), list("yx")) == pytest.approx(-1.0)

    def test_one_label_throughout_is_undefined(self) -> None:
        assert cohens_kappa(list("xxx"), list("xxx")) is None
        assert cohens_kappa([], []) is None


class TestComparing:
    def test_identical_annotations_agree_on_everything(self) -> None:
        result = compare([clip()], [clip()])
        assert result.clips == 1
        assert result.miou == 1.0
        assert result.boundary_error_s == 0.0
        assert result.frame_agreement == 1.0 and result.kappa == 1.0
        assert result.primary_view == 1.0 and result.event_type == 1.0
        assert result.iou_by_phase["baseline"] == 1.0 and result.iou_by_phase["action"] == 1.0

    def test_phases_nobody_marked_are_not_counted(self) -> None:
        result = compare([clip()], [clip()])
        assert result.iou_by_phase["precursor"] is None
        assert result.presence_by_phase["precursor"] == 1.0  # both agree it does not happen

    def test_a_shifted_boundary_lowers_iou_and_is_measured_in_seconds(self) -> None:
        a = clip(phases=[("baseline", 0, 10), ("action", 10, 20)])
        b = clip(phases=[("baseline", 0, 12), ("action", 12, 20)])
        result = compare([a], [b])
        assert result.iou_by_phase["baseline"] == pytest.approx(10 / 12)
        assert result.iou_by_phase["action"] == pytest.approx(8 / 10)
        # starts differ by 0 and 2, ends by 2 and 0: mean 1.0
        assert result.boundary_error_s == pytest.approx(1.0)

    def test_a_phase_only_one_marked_has_zero_iou_and_no_presence_agreement(self) -> None:
        a = clip(phases=[("baseline", 0, 10), ("action", 10, 20)])
        b = clip(phases=[("baseline", 0, 10), ("escalation", 10, 15), ("action", 15, 20)])
        result = compare([a], [b])
        assert result.iou_by_phase["escalation"] == 0.0
        assert result.presence_by_phase["escalation"] == 0.0
        assert result.presence_by_phase["baseline"] == 1.0

    def test_boundary_error_only_counts_phases_both_marked(self) -> None:
        a = clip(phases=[("baseline", 0, 10)])
        b = clip(phases=[("baseline", 0, 10), ("action", 10, 20)])
        assert compare([a], [b]).boundary_error_s == 0.0

    def test_miou_is_the_mean_over_phases_not_over_clips(self) -> None:
        a1 = clip("c1", [("baseline", 0, 10)])
        b1 = clip("c1", [("baseline", 0, 10)])  # baseline IoU 1
        a2 = clip("c2", [("baseline", 0, 10), ("action", 10, 20)])
        b2 = clip("c2", [("baseline", 5, 15), ("action", 15, 20)])  # 1/3 and 5/10
        result = compare([a1, a2], [b1, b2])
        assert result.iou_by_phase["baseline"] == pytest.approx((1 + 5 / 15) / 2)
        assert result.iou_by_phase["action"] == pytest.approx(0.5)
        assert result.miou == pytest.approx(((1 + 5 / 15) / 2 + 0.5) / 2)

    def test_only_clips_both_labelled_are_compared(self) -> None:
        result = compare([clip("a"), clip("b")], [clip("b"), clip("c")])
        assert result.clips == 1

    def test_the_view_and_event_type_they_chose(self) -> None:
        a = [clip("c1", primary="cam02", event_type="theft"), clip("c2", primary="cam02")]
        b = [clip("c1", primary="cam04", event_type="theft"), clip("c2", primary="cam02")]
        result = compare(a, b)
        assert result.primary_view == 0.5 and result.event_type == 1.0

    def test_the_least_agreed_clips_come_first(self) -> None:
        good = clip("good", [("baseline", 0, 10)])
        bad_a = clip("bad", [("baseline", 0, 10)])
        bad_b = clip("bad", [("baseline", 8, 18)])
        result = compare([good, bad_a], [good, bad_b])
        assert list(result.clip_miou) == ["bad", "good"]

    def test_frame_agreement_and_kappa_come_from_the_grid(self) -> None:
        a = clip(phases=[("baseline", 0, 5), ("action", 5, 10)])
        b = clip(phases=[("baseline", 0, 5), ("action", 6, 10)])  # differ over one second of ten
        result = compare([a], [b])
        assert result.frame_agreement == pytest.approx(0.9)
        assert 0.7 < result.kappa < 1.0

    def test_nothing_in_common_is_not_a_crash(self) -> None:
        result = compare([clip("a")], [clip("b")])
        assert result.clips == 0 and result.miou is None and result.frame_agreement is None
        assert result.primary_view is None


class TestReporting:
    def test_markdown_has_a_row_per_phase_and_the_summary(self) -> None:
        text = render_markdown(compare([clip()], [clip()]))
        assert "| baseline | 100.0% | 100.0% |" in text
        assert "| precursor | n/a | 100.0% |" in text
        assert "- mIoU: 100.0%" in text and "Cohen's kappa 1.00" in text
        assert "Mean boundary difference (phases both marked): 0.00 s" in text

    def test_it_warns_when_the_overlap_set_is_too_small(self) -> None:
        text = render_markdown(compare([clip()], [clip()]), expected_clips=20)
        assert "WARNING: the overlap set should have 20 clips; only 1" in text

    def test_no_warning_when_there_are_enough_or_nothing_is_expected(self) -> None:
        assert "WARNING" not in render_markdown(compare([clip()], [clip()]), expected_clips=1)
        assert "WARNING" not in render_markdown(compare([clip()], [clip()]))

    def test_it_lists_the_clips_to_look_at_first(self) -> None:
        a, b = clip("bad", [("baseline", 0, 10)]), clip("bad", [("baseline", 8, 18)])
        assert "- bad:" in render_markdown(compare([a], [b]))

    def test_an_empty_comparison_renders(self) -> None:
        assert "n/a" in render_markdown(Agreement())

    def test_as_json(self) -> None:
        data = compare([clip()], [clip()]).as_dict()
        assert data["miou"] == 1.0 and data["clips"] == 1
        assert set(data["iou_by_phase"]) == {
            "baseline",
            "precursor",
            "escalation",
            "action",
            "aftermath",
        }


class TestTheGridExactly:
    def test_a_phase_ending_on_a_grid_midpoint_does_not_cover_that_point(self) -> None:
        labels = frame_labels(clip(phases=[("baseline", 0, 0.25)]), 0.4)
        assert labels == ["baseline", "baseline", "none", "none"]  # the third point is at 0.25

    def test_points_are_taken_in_the_middle_of_their_cell(self) -> None:
        # 0.05-0.25 covers the cell middles 0.05 and 0.15 but not 0.25; sampled at the left
        # edges (0.0, 0.1, 0.2) it would be a different list
        labels = frame_labels(clip(phases=[("baseline", 0.05, 0.25)]), 0.3)
        assert labels == ["baseline", "baseline", "none"]


class TestLongerThanEitherThoughtAtFirst:
    def test_time_only_one_annotator_marked_counts_against_agreement(self) -> None:
        a = clip(phases=[("baseline", 0, 5)])
        b = clip(phases=[("baseline", 0, 8)])
        result = compare([a], [b])
        assert result.frame_agreement == pytest.approx(5 / 8)


class TestTheListOfDisputedClips:
    def test_the_five_least_agreed_clips_are_listed_and_no_more(self) -> None:
        a = [clip(f"c{n}", [("baseline", 0, 10)]) for n in range(7)]
        b = [clip(f"c{n}", [("baseline", n, 10 + n)]) for n in range(7)]
        text = render_markdown(compare(a, b))
        listed = [line for line in text.splitlines() if line.startswith("- c")]
        assert len(listed) == 5 and listed[0].startswith("- c6:")
