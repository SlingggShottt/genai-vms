from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from annotation_kit.candidates import PhaseCandidate, ViewSpec
from annotation_kit.phaseconvert import (
    SKIP_REASONS,
    SNAP_FRAMES,
    convert_phases,
    read_export,
    summarise,
    write_phase_labels,
)
from annotation_kit.phasetasks import phase_task
from annotation_kit.tasks import read_phase_labels, tasks_from_clips


def candidate() -> PhaseCandidate:
    return PhaseCandidate(
        candidate_id="meva:clip-1:act:7",
        dataset="meva",
        source_video="meva:3-420:slot",
        event_type="activity",
        primary_view="G420",
        views=[
            ViewSpec(camera="G420", source_uri="s3://src/a.avi", start_s=10, end_s=50),
            ViewSpec(camera="G419", source_uri="s3://src/b.avi", start_s=11, end_s=51),
        ],
    )


def ranges(*spans: tuple[str, int, int]) -> list[dict[str, Any]]:
    """Timeline results the way Label Studio exports them: frames at 30 fps."""
    return [
        {
            "from_name": "phase",
            "to_name": "video",
            "type": "timelinelabels",
            "value": {"ranges": [{"start": s, "end": e}], "timelinelabels": [phase]},
        }
        for phase, s, e in spans
    ]


def choices(**picked: str) -> list[dict[str, Any]]:
    return [
        {"from_name": k, "to_name": "video", "type": "choices", "value": {"choices": [v]}}
        for k, v in picked.items()
    ]


def item(result=None, *, annotations=None, **data_over):  # noqa: ANN001, ANN003, ANN201
    data = phase_task(candidate(), clip_prefix="s3://vms/clips")["data"]
    data.update(data_over)
    if annotations is None:
        annotations = [
            {
                "id": 1,
                "was_cancelled": False,
                "completed_by": {"id": 3, "email": "k@example.com"},
                "updated_at": "2026-10-05T10:00:00Z",
                "result": result
                if result is not None
                else ranges(("baseline", 0, 300), ("action", 300, 900))
                + choices(usable="Yes", primary_view="G420", event_type="activity"),
            }
        ]
    return {"id": 1, "data": data, "annotations": annotations}


def one(result, **kw):  # noqa: ANN001, ANN003, ANN201
    converted = convert_phases([item(result, **kw)])
    assert len(converted.clips) == 1, dict(converted.skipped)
    return converted


class TestAnAnnotatedClip:
    def test_frames_become_seconds_from_the_start_of_the_clip(self) -> None:
        clip = one(None).clips[0]
        assert [(p.phase, p.start_s, p.end_s) for p in clip.phases] == [
            ("baseline", 0.0, 10.0),
            ("action", 10.0, 30.0),
        ]

    def test_the_label_describes_the_clip_and_its_cut_views(self) -> None:
        clip = one(None).clips[0]
        assert clip.clip_id == "meva:clip-1:act:7" and clip.source_video == "meva:3-420:slot"
        assert clip.schema_version == "phase_labels.v1" and clip.annotator == "k@example.com"
        assert [(v.camera, v.video_uri) for v in clip.views] == [
            ("G420", "s3://vms/clips/meva_clip-1_act_7/G420.mp4"),
            ("G419", "s3://vms/clips/meva_clip-1_act_7/G419.mp4"),
        ]

    def test_the_annotators_primary_view_and_event_type_win_over_the_suggestion(self) -> None:
        result = ranges(("action", 0, 90)) + choices(
            usable="Yes", primary_view="G419", event_type="theft"
        )
        clip = one(result).clips[0]
        assert (clip.primary_view, clip.event_type) == ("G419", "theft")

    def test_without_their_choices_the_suggestion_stands(self) -> None:
        clip = one(ranges(("action", 0, 90))).clips[0]
        assert (clip.primary_view, clip.event_type) == ("G420", "activity")

    def test_a_primary_view_that_is_not_a_view_of_the_clip_falls_back_to_the_suggestion(
        self,
    ) -> None:
        clip = one(ranges(("action", 0, 90)) + choices(primary_view="G999")).clips[0]
        assert clip.primary_view == "G420"

    def test_gaps_between_phases_are_fine(self) -> None:
        clip = one(ranges(("baseline", 0, 90), ("action", 300, 600))).clips[0]
        assert [(p.start_s, p.end_s) for p in clip.phases] == [(0, 3), (10, 20)]

    def test_phases_may_touch(self) -> None:
        assert len(one(ranges(("baseline", 0, 90), ("precursor", 90, 180))).clips[0].phases) == 2

    def test_a_phase_may_be_left_out(self) -> None:
        phases = one(ranges(("baseline", 0, 90), ("aftermath", 300, 600))).clips[0].phases
        assert [p.phase for p in phases] == ["baseline", "aftermath"]

    def test_the_frame_rate_is_configurable(self) -> None:
        converted = convert_phases([item(ranges(("action", 0, 50)))], fps=25)
        assert converted.clips[0].phases[0].end_s == 2.0

    def test_ranges_are_sorted_by_time_whatever_order_they_were_drawn_in(self) -> None:
        clip = one(ranges(("action", 300, 600), ("baseline", 0, 90))).clips[0]
        assert [p.phase for p in clip.phases] == ["baseline", "action"]

    def test_a_label_with_two_ranges_is_one_phase_marked_twice(self) -> None:
        result = [
            {
                "from_name": "phase",
                "to_name": "video",
                "type": "timelinelabels",
                "value": {
                    "ranges": [{"start": 0, "end": 90}, {"start": 300, "end": 390}],
                    "timelinelabels": ["action"],
                },
            }
        ]
        converted = convert_phases([item(result)])
        assert converted.clips == [] and converted.skipped["repeated_phase"]


class TestWhichAnnotation:
    def ann(self, id_: int, when: str, result, cancelled: bool = False):  # noqa: ANN001, ANN201
        return {
            "id": id_,
            "was_cancelled": cancelled,
            "updated_at": when,
            "completed_by": id_,
            "result": result,
        }

    def test_the_latest_finished_one_wins(self) -> None:
        old = self.ann(9, "2026-10-05T09:00:00Z", ranges(("baseline", 0, 90)))
        new = self.ann(2, "2026-10-05T11:00:00Z", ranges(("action", 0, 90)))
        assert one(None, annotations=[old, new]).clips[0].phases[0].phase == "action"
        assert one(None, annotations=[new, old]).clips[0].phases[0].phase == "action"

    def test_a_cancelled_one_is_ignored(self) -> None:
        done = self.ann(1, "2026-10-05T09:00:00Z", ranges(("baseline", 0, 90)))
        skipped = self.ann(2, "2026-10-05T11:00:00Z", ranges(("action", 0, 90)), cancelled=True)
        assert one(None, annotations=[done, skipped]).clips[0].phases[0].phase == "baseline"

    def test_the_annotator_is_named_by_email_then_id_then_nothing(self) -> None:
        def named(by):  # noqa: ANN001, ANN202
            a = self.ann(1, "x", ranges(("action", 0, 90)))
            a["completed_by"] = by
            return one(None, annotations=[a]).clips[0].annotator

        assert named({"id": 7, "email": "p@example.com"}) == "p@example.com"
        assert named({"id": 7}) == "7" and named(7) == "7" and named(None) is None


class TestSkipping:
    def why(self, result=None, **kw) -> dict[str, list[str]]:  # noqa: ANN003
        converted = convert_phases([item(result, **kw)])
        assert converted.clips == []
        return {k: v for k, v in converted.skipped.items() if v}

    def test_a_clip_nobody_labelled(self) -> None:
        assert list(self.why(annotations=[])) == ["no_annotation"]

    def test_only_cancelled_or_empty_annotations(self) -> None:
        assert list(
            self.why(
                annotations=[{"id": 1, "was_cancelled": True, "result": ranges(("action", 0, 9))}]
            )
        ) == ["cancelled"]
        assert list(self.why(annotations=[{"id": 1, "was_cancelled": False, "result": []}])) == [
            "cancelled"
        ]

    def test_an_unusable_clip_even_with_phases_marked(self) -> None:
        assert list(self.why(ranges(("action", 0, 90)) + choices(usable="No"))) == ["unusable"]

    def test_a_clip_with_no_phases(self) -> None:
        assert list(self.why(choices(usable="Yes"))) == ["no_phases"]

    @pytest.mark.parametrize("span", [("action", 90, 90), ("action", 90, 30), ("action", -5, 30)])
    def test_a_range_that_is_empty_backwards_or_before_the_start(self, span) -> None:  # noqa: ANN001
        assert list(self.why(ranges(span))) == ["bad_range"]

    def test_the_same_phase_marked_in_two_places(self) -> None:
        assert list(self.why(ranges(("action", 0, 90), ("action", 300, 600)))) == ["repeated_phase"]

    def test_phases_in_the_wrong_order(self) -> None:
        assert list(self.why(ranges(("action", 0, 90), ("baseline", 90, 300)))) == ["out_of_order"]

    def test_a_real_overlap(self) -> None:
        assert list(
            self.why(ranges(("baseline", 0, 90), ("precursor", 90 - SNAP_FRAMES - 1, 300)))
        ) == ["overlap"]

    def test_every_reason_is_a_known_one_and_is_counted_in_the_total(self) -> None:
        converted = convert_phases(
            [
                item(),
                item(annotations=[]),
                item(choices(usable="No")),
                item(ranges(("action", 90, 90))),
            ]
        )
        assert set(converted.skipped) <= set(SKIP_REASONS)
        assert converted.tasks == 4 and len(converted.clips) == 1

    def test_a_task_that_is_not_a_phase_task_is_an_error_not_a_skip(self) -> None:
        with pytest.raises(ValueError, match="not a phase task"):
            convert_phases([{"data": {"candidate_id": "x"}, "annotations": []}])


class TestSnappingBoundaries:
    @pytest.mark.parametrize("overlap", range(1, SNAP_FRAMES + 1))
    def test_a_few_frames_of_overlap_is_snapped_to_touch(self, overlap: int) -> None:
        converted = one(ranges(("baseline", 0, 90), ("precursor", 90 - overlap, 300)))
        spans = converted.clips[0].phases
        assert spans[1].start_s == spans[0].end_s == 3.0
        assert converted.snapped == 1

    def test_an_exact_touch_is_not_a_snap(self) -> None:
        assert one(ranges(("baseline", 0, 90), ("precursor", 90, 300))).snapped == 0

    def test_snaps_are_counted_and_reported(self) -> None:
        converted = one(ranges(("baseline", 0, 90), ("precursor", 88, 200), ("action", 198, 300)))
        assert converted.snapped == 2
        assert "2 phase boundaries were snapped" in summarise(converted)


class TestTheClipsLength:
    def test_a_phase_that_runs_past_the_end_is_cut_to_it(self) -> None:
        clip = one(ranges(("action", 900, 1500)), duration_s=40.0).clips[
            0
        ]  # 30 s to 50 s of a 40 s clip
        assert (clip.phases[0].start_s, clip.phases[0].end_s) == (30.0, 40.0)

    def test_a_phase_that_starts_after_the_end_is_dropped(self) -> None:
        clip = one(ranges(("baseline", 0, 90), ("action", 1500, 1800)), duration_s=40.0).clips[0]
        assert [p.phase for p in clip.phases] == ["baseline"]

    def test_if_nothing_is_left_the_clip_has_no_phases(self) -> None:
        converted = convert_phases([item(ranges(("action", 1500, 1800)), duration_s=40.0)])
        assert converted.skipped["no_phases"]

    def test_with_no_known_length_nothing_is_cut(self) -> None:
        data = phase_task(candidate(), clip_prefix="p")["data"]
        del data["duration_s"]
        raw = {
            "data": data,
            "annotations": [
                {"id": 1, "was_cancelled": False, "result": ranges(("action", 0, 9000))}
            ],
        }
        assert convert_phases([raw]).clips[0].phases[0].end_s == 300.0


class TestTheContractWithTheCaptionVqaKit:
    """phase_labels.jsonl is what `annotation-kit tasks` (P3-J6) reads: the two must fit."""

    def test_the_output_is_read_back_by_the_caption_kits_reader_and_becomes_its_tasks(
        self, tmp_path: Path
    ) -> None:
        converted = convert_phases([item(), item(candidate_id="meva:clip-2:act:8")])
        path = tmp_path / "phase_labels.jsonl"
        assert write_phase_labels(converted.clips, path) == 2
        clips = read_phase_labels(path)
        assert clips == converted.clips
        tasks = list(tasks_from_clips(clips))
        assert len(tasks) == 2 * 2 * 2  # 2 clips x 2 phases x 2 views
        assert {t.view for t in tasks} == {"G420", "G419"}
        assert tasks[0].view == "G420"  # the primary view first

    def test_the_proposed_example_is_the_same_shape(self, repo: Path) -> None:
        example = json.loads((repo / "ml/annotation/phase_export_example.json").read_text())
        written = json.loads(convert_phases([item()]).clips[0].model_dump_json())
        assert set(example) == set(written)


class TestFiles:
    def test_reads_an_export_and_refuses_anything_that_is_not_a_list(self, tmp_path: Path) -> None:
        good = tmp_path / "e.json"
        good.write_text(json.dumps([item()]))
        assert len(read_export(good)) == 1
        bad = tmp_path / "b.json"
        bad.write_text("{}")
        with pytest.raises(ValueError, match="a JSON list of tasks"):
            read_export(bad)

    def test_the_summary_counts_and_says_what_was_skipped(self) -> None:
        converted = convert_phases([item(), item(annotations=[])])
        text = summarise(converted)
        assert (
            text.startswith("1 of 2 tasks became phase labels.")
            and "Skipped: 1 no_annotation" in text
        )


class TestTheSnapLimitAsWritten:
    """Three frames of overlap is snapped, four is a real overlap (the numbers as written)."""

    def test_three_frames_snap_and_four_do_not(self) -> None:
        assert one(ranges(("baseline", 0, 90), ("precursor", 87, 300))).snapped == 1
        converted = convert_phases([item(ranges(("baseline", 0, 90), ("precursor", 86, 300)))])
        assert converted.skipped["overlap"] and converted.clips == []

    def test_the_constant_is_three(self) -> None:
        assert SNAP_FRAMES == 3


class TestAPhaseStartingAtTheEndOfTheClip:
    def test_is_dropped_rather_than_crashing(self) -> None:
        # a 40 s clip, a phase starting exactly at 40 s: nothing of it is inside the clip
        clip = one(ranges(("baseline", 0, 90), ("action", 1200, 1500)), duration_s=40.0).clips[0]
        assert [p.phase for p in clip.phases] == ["baseline"]
