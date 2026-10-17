from __future__ import annotations

import json
from pathlib import Path

import pytest
from annotation_kit import weaklabels
from annotation_kit.candidates import PhaseCandidate, ViewSpec, write_candidates
from annotation_kit.cli import main
from annotation_kit.tasks import read_phase_labels
from annotation_kit.ucf import Span


def cand(
    name: str = "Abuse028_x264", start: float = 0.0, end: float = 18.0, dataset: str = "ucf_crime"
):
    return PhaseCandidate(
        candidate_id=f"{dataset}:{name}",
        dataset=dataset,  # type: ignore[arg-type]
        source_video=f"{dataset}:{name}",
        event_type="abuse",
        activity="Abuse",
        primary_view="cam01",
        views=[ViewSpec(camera="cam01", source_uri=f"ucf://{name}.mp4", start_s=start, end_s=end)],
    )


def stages(items) -> list[tuple[str, float, float]]:  # noqa: ANN001
    return [(p.phase, p.start_s, p.end_s) for p in items]


class TestPhasesFromASpan:
    def test_before_during_and_after(self) -> None:
        assert stages(weaklabels.phases_from_span(10, 15, 18)) == [
            ("baseline", 0, 10),
            ("action", 10, 15),
            ("aftermath", 15, 18),
        ]

    def test_a_span_that_starts_at_the_start_has_no_baseline(self) -> None:
        assert [p[0] for p in stages(weaklabels.phases_from_span(0, 5, 18))] == [
            "action",
            "aftermath",
        ]

    def test_a_span_that_runs_to_the_end_has_no_aftermath(self) -> None:
        assert [p[0] for p in stages(weaklabels.phases_from_span(10, 18, 18))] == [
            "baseline",
            "action",
        ]

    def test_a_span_longer_than_the_clip_is_cut_to_it(self) -> None:
        assert stages(weaklabels.phases_from_span(10, 90, 40)) == [
            ("baseline", 0, 10),
            ("action", 10, 40),
        ]

    def test_a_stage_under_a_second_is_left_out_like_a_marked_one_would_be(self) -> None:
        assert [p[0] for p in stages(weaklabels.phases_from_span(0.5, 5, 5.5))] == ["action"]

    def test_exactly_a_second_is_kept(self) -> None:
        got = stages(weaklabels.phases_from_span(1, 5, 6))
        assert [p[0] for p in got] == ["baseline", "action", "aftermath"]

    def test_a_crime_under_a_second_gives_nothing(self) -> None:
        assert weaklabels.phases_from_span(10, 10.9, 40) == []

    def test_the_stages_touch_and_never_overlap(self) -> None:
        got = weaklabels.phases_from_span(7.5, 22.5, 40)
        assert all(a.end_s == b.start_s for a, b in zip(got, got[1:], strict=False))


class TestTheSpanInTheClip:
    def test_is_measured_from_the_start_of_the_clip_not_the_video(self) -> None:
        assert weaklabels.span_in_clip([Span(100, 130)], window_start_s=90, duration_s=60) == (
            10,
            40,
        )

    def test_two_spans_run_from_the_first_start_to_the_last_end(self) -> None:
        spans = [Span(12, 15), Span(25, 30)]
        assert weaklabels.span_in_clip(spans, 10, 40) == (2, 20)

    def test_a_span_outside_the_clip_is_ignored_and_one_inside_is_kept(self) -> None:
        spans = [
            Span(146, 155.7),
            Span(10, 17),
        ]  # the second Shoplifting007 span is far past the clip
        assert weaklabels.span_in_clip(spans, 0, 40) == (10, 17)

    def test_nothing_in_the_clip_is_none(self) -> None:
        assert weaklabels.span_in_clip([Span(146, 155)], 0, 40) is None
        assert weaklabels.span_in_clip([Span(0, 5)], 20, 40) is None

    def test_a_span_that_starts_before_the_clip_is_cut_at_its_start(self) -> None:
        assert weaklabels.span_in_clip([Span(5, 30)], 10, 40) == (0, 20)


class TestTheLabel:
    def test_it_describes_the_clip_and_says_it_was_not_made_by_a_person(self) -> None:
        label = weaklabels.weak_label(cand(), [Span(10, 15)], clip_prefix="local://clips")
        assert label is not None
        assert label.clip_id == "ucf_crime:Abuse028_x264" and label.event_type == "abuse"
        assert label.annotator == weaklabels.WEAK_ANNOTATOR == "dataset-span:ucf-crime"
        assert [(v.camera, v.video_uri) for v in label.views] == [
            ("cam01", "local://clips/ucf_crime_Abuse028_x264/cam01.mp4")
        ]
        assert stages(label.phases) == [
            ("baseline", 10 - 10, 10),
            ("action", 10, 15),
            ("aftermath", 15, 18),
        ]

    def test_the_window_start_is_taken_off(self) -> None:
        label = weaklabels.weak_label(cand(start=40, end=80), [Span(55, 70)], clip_prefix="p")
        assert label is not None and stages(label.phases)[:2] == [
            ("baseline", 0, 15),
            ("action", 15, 30),
        ]

    def test_a_crime_outside_the_window_gives_no_label(self) -> None:
        assert weaklabels.weak_label(cand(), [Span(300, 320)], clip_prefix="p") is None

    def test_only_ucf_crime_has_spans(self) -> None:
        with pytest.raises(weaklabels.WeakLabelError, match="only known for UCF-Crime"):
            weaklabels.weak_label(cand(dataset="meva"), [Span(1, 5)], clip_prefix="p")


class TestWhichClipsWereSkipped:
    def task(self, name: str, annotations: list[dict]) -> dict:
        return {"data": {"candidate_id": f"ucf_crime:{name}"}, "annotations": annotations}

    def test_a_clip_whose_only_annotation_is_a_skip(self) -> None:
        export = [self.task("A", [{"was_cancelled": True, "result": []}])]
        assert weaklabels.skipped_in(export) == {"ucf_crime:A"}

    def test_a_clip_with_a_real_mark_is_not_skipped_even_if_it_was_also_skipped_once(self) -> None:
        export = [
            self.task(
                "A",
                [
                    {"was_cancelled": True, "result": []},
                    {"was_cancelled": False, "result": [{"x": 1}]},
                ],
            )
        ]
        assert weaklabels.skipped_in(export) == set()

    def test_a_submitted_annotation_with_nothing_in_it_counts_as_skipped(self) -> None:
        assert weaklabels.skipped_in(
            [self.task("A", [{"was_cancelled": False, "result": []}])]
        ) == {"ucf_crime:A"}

    def test_a_cancelled_annotation_that_has_marks_does_not_count_as_a_mark(self) -> None:
        export = [self.task("A", [{"was_cancelled": True, "result": [{"x": 1}]}])]
        assert weaklabels.skipped_in(export) == {"ucf_crime:A"}

    def test_a_task_nobody_opened_is_not_listed(self) -> None:
        assert weaklabels.skipped_in([self.task("A", [])]) == set()


class TestTheCommand:
    @pytest.fixture
    def files(self, tmp_path: Path) -> dict[str, Path]:
        candidates = tmp_path / "candidates.json"
        write_candidates(
            [
                cand("Abuse028_x264", 0, 18),
                cand("Arrest001_x264", 30, 70),
                cand("Burglary005_x264", 0, 40),
                cand("Fighting003_x264", 0, 30),
            ],
            candidates,
        )
        labels = tmp_path / "labels.txt"
        labels.write_text(
            "Abuse028_x264.mp4  Abuse  300  450  -1  -1  \n"  # 10-15 s
            "Arrest001_x264.mp4  Arrest  1185  1485  -1  -1  \n"  # 9.5-19.5 s in a clip from 30 s
            "Burglary005_x264.mp4  Burglary  9000  9900  -1  -1  \n"  # far past the window
        )
        export = tmp_path / "export.json"
        skip = {"was_cancelled": True, "result": []}
        done = {"was_cancelled": False, "result": [{"x": 1}]}
        export.write_text(json.dumps([
            {"data": {"candidate_id": "ucf_crime:Abuse028_x264"}, "annotations": [skip]},
            {"data": {"candidate_id": "ucf_crime:Arrest001_x264"}, "annotations": [skip]},
            {"data": {"candidate_id": "ucf_crime:Fighting003_x264"}, "annotations": [done]},
        ]))  # fmt: skip
        return {
            "candidates": candidates,
            "labels": labels,
            "export": export,
            "out": tmp_path / "weak.jsonl",
        }

    def run(self, files: dict[str, Path], *extra: str) -> int:
        return main(
            [
                "span-labels",
                str(files["candidates"]),
                "--annotations",
                str(files["labels"]),
                "--out",
                str(files["out"]),
                *extra,
            ]
        )

    def test_labels_exactly_the_skipped_clips_and_says_what_it_made(self, files, capsys) -> None:
        assert self.run(files, "--skipped-in", str(files["export"])) == 0
        clips = read_phase_labels(files["out"])
        assert sorted(c.clip_id for c in clips) == [
            "ucf_crime:Abuse028_x264",
            "ucf_crime:Arrest001_x264",
        ]
        assert all(
            c.annotator == weaklabels.WEAK_ANNOTATOR for c in clips
        )  # not Fighting003: a person marked it
        out = capsys.readouterr().out
        assert "| ucf_crime:Abuse028_x264 | baseline 0-10, action 10-15, aftermath 15-18 |" in out
        assert "2 labels from the dataset's spans" in out and "dataset-span:ucf-crime" in out

    def test_the_times_are_the_clips_not_the_videos(self, files) -> None:
        self.run(files, "--skipped-in", str(files["export"]))
        arrest = next(c for c in read_phase_labels(files["out"]) if "Arrest" in c.clip_id)
        assert [(p.phase, p.start_s, p.end_s) for p in arrest.phases] == [
            ("baseline", 0, 9.5), ("action", 9.5, 19.5), ("aftermath", 19.5, 40)
        ]  # fmt: skip

    def test_a_clip_can_be_named_and_one_can_be_left_out(self, files) -> None:
        assert (
            self.run(
                files,
                "--only",
                "ucf_crime:Abuse028_x264",
                "--only",
                "ucf_crime:Arrest001_x264",
                "--exclude",
                "ucf_crime:Arrest001_x264",
            )
            == 0
        )
        assert [c.clip_id for c in read_phase_labels(files["out"])] == ["ucf_crime:Abuse028_x264"]

    def test_a_crime_outside_the_window_or_missing_from_the_file_is_reported_and_exit_is_1(
        self, files, capsys
    ) -> None:
        code = self.run(
            files,
            "--only",
            "ucf_crime:Burglary005_x264",
            "--only",
            "ucf_crime:Fighting003_x264",
            "--only",
            "ucf_crime:Nope001_x264",
            "--only",
            "ucf_crime:Abuse028_x264",
        )
        err = capsys.readouterr().err
        assert code == 1
        assert "Burglary005_x264: the crime is not inside the clip" in err
        assert "Fighting003_x264: the annotation file has no crime span for it" in err
        assert "Nope001_x264: not in the candidates file" in err
        assert [c.clip_id for c in read_phase_labels(files["out"])] == [
            "ucf_crime:Abuse028_x264"
        ]  # the rest is still written

    def test_nothing_selected_is_a_usage_error_and_writes_nothing(self, files, capsys) -> None:
        assert self.run(files) == 2
        assert "nothing selected" in capsys.readouterr().err and not files["out"].exists()

    def test_it_never_writes_to_the_hand_labelled_file(self, files, tmp_path: Path) -> None:
        hand = tmp_path / "phase_labels.jsonl"
        hand.write_text("keep me\n")
        self.run(files, "--skipped-in", str(files["export"]))
        assert hand.read_text() == "keep me\n" and files["out"] != hand

    def test_the_clip_prefix_decides_where_the_clips_are_said_to_be(self, files) -> None:
        self.run(files, "--only", "ucf_crime:Abuse028_x264", "--clip-prefix", "s3://vms/clips")
        (clip,) = read_phase_labels(files["out"])
        assert clip.views[0].video_uri == "s3://vms/clips/ucf_crime_Abuse028_x264/cam01.mp4"
