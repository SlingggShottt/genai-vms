from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from annotation_kit.ucf import (
    DEFAULT_CLASSES,
    Span,
    UcfConfig,
    UcfVideo,
    probe_duration,
    read_temporal_annotations,
    scan_videos,
    select_candidates,
    summarise,
)

ANNOTATIONS = """\
Abuse028_x264.mp4  Abuse  165  240  -1  -1
Arrest001_x264.mp4  Arrest  300  600  900  1050
Normal_Videos_010_x264.mp4  Normal  -1  -1  -1  -1
Robbery050_x264.mp4  Robbery  45  90  -1  -1

short line
"""


@pytest.fixture
def annotations(tmp_path: Path):  # noqa: ANN201
    path = tmp_path / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt"
    path.write_text(ANNOTATIONS)
    return read_temporal_annotations(path)


class TestTheAnnotationFile:
    def test_reads_the_class_and_the_span_in_seconds(self, annotations) -> None:  # noqa: ANN001
        cls, spans = annotations["Abuse028_x264.mp4"]
        assert cls == "Abuse" and spans == [Span(5.5, 8.0)]  # frames 165-240 at 30 fps

    def test_a_second_span_is_a_second_span(self, annotations) -> None:  # noqa: ANN001
        assert annotations["Arrest001_x264.mp4"][1] == [Span(10.0, 20.0), Span(30.0, 35.0)]

    def test_minus_one_means_no_span(self, annotations) -> None:  # noqa: ANN001
        assert annotations["Normal_Videos_010_x264.mp4"][1] == []

    def test_lines_that_are_not_rows_are_skipped(self, annotations) -> None:  # noqa: ANN001
        assert len(annotations) == 4

    def test_a_span_that_ends_before_it_starts_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "a.txt"
        path.write_text(
            "Abuse001_x264.mp4 Abuse 300 200 -1 -1\nAbuse002_x264.mp4 Abuse x y -1 -1\n"
        )
        read = read_temporal_annotations(path)
        assert read["Abuse001_x264.mp4"][1] == [] and read["Abuse002_x264.mp4"][1] == []


class TestFindingVideos:
    def test_finds_videos_in_the_chosen_classes_by_their_folder(self, tmp_path: Path) -> None:
        for folder, name in [
            ("Abuse", "Abuse001_x264.mp4"),
            ("Arson", "Arson001_x264.mp4"),
            ("abuse", "Abuse002.avi"),
        ]:
            (tmp_path / "Videos" / folder).mkdir(parents=True, exist_ok=True)
            (tmp_path / "Videos" / folder / name).write_bytes(b"")
        (tmp_path / "Videos/Abuse/readme.txt").write_text("not a video")
        found = scan_videos(tmp_path, ["Abuse", "Fighting"])
        assert [(v.name, v.cls, v.path) for v in found] == [
            ("Abuse001_x264.mp4", "Abuse", "Videos/Abuse/Abuse001_x264.mp4"),
            ("Abuse002.avi", "Abuse", "Videos/abuse/Abuse002.avi"),
        ]

    def test_an_empty_folder_has_no_videos(self, tmp_path: Path) -> None:
        assert scan_videos(tmp_path, DEFAULT_CLASSES) == []


class TestProbing:
    def test_a_missing_file_or_tool_is_none_not_an_error(self, tmp_path: Path) -> None:
        assert probe_duration(tmp_path / "nope.mp4") is None


def video(
    name: str = "Abuse028_x264.mp4", cls: str = "Abuse", duration: float | None = 120
) -> UcfVideo:
    return UcfVideo(name, cls, f"Videos/{cls}/{name}", duration)


class TestSelecting:
    def pick(self, videos, annotations, **config):  # noqa: ANN001, ANN003, ANN201
        return select_candidates(videos, annotations, UcfConfig(per_class_cap=None, **config))

    def test_a_video_with_a_span_is_cut_around_it(self, annotations) -> None:  # noqa: ANN001
        c = self.pick([video()], annotations).candidates[0]  # span 5.5-8.0 s
        assert (c.views[0].start_s, c.views[0].end_s) == (
            0.0,
            18.0,
        )  # 10 s before is before 0: clamp
        assert c.note == "around the annotated anomaly"

    def test_two_spans_are_covered_from_the_first_to_the_last(self, annotations) -> None:  # noqa: ANN001
        c = self.pick([video("Arrest001_x264.mp4", "Arrest")], annotations).candidates[0]
        assert (c.views[0].start_s, c.views[0].end_s) == (0.0, 45.0)  # 10-35 s, 10 s either side

    def test_a_video_without_a_span_is_offered_from_its_start(self, annotations) -> None:  # noqa: ANN001
        c = self.pick([video("Abuse001_x264.mp4")], annotations).candidates[0]
        assert (c.views[0].start_s, c.views[0].end_s) == (0.0, 90.0)
        assert c.note == "untrimmed: anomaly not located"

    def test_the_window_never_runs_past_the_end_of_the_video(self, annotations) -> None:  # noqa: ANN001
        c = self.pick([video(duration=12)], annotations).candidates[0]
        assert c.views[0].end_s == 12

    def test_a_very_long_anomaly_keeps_its_start_and_is_noted(self, tmp_path: Path) -> None:
        path = tmp_path / "a.txt"
        path.write_text("Fighting001_x264.mp4 Fighting 3000 9000 -1 -1\n")  # 100-300 s
        sel = self.pick(
            [video("Fighting001_x264.mp4", "Fighting", None)], read_temporal_annotations(path)
        )
        view = sel.candidates[0].views[0]
        assert (view.start_s, view.end_s) == (90.0, 180.0)
        assert sel.skipped["window_shortened"] == 1

    def test_a_video_too_short_to_phase_is_noted_and_left_out(self, annotations) -> None:  # noqa: ANN001
        sel = self.pick([video(duration=0.5)], annotations)
        assert sel.candidates == [] and sel.skipped["too_short"] == 1

    def test_the_event_type_is_the_class_in_lower_case(self, annotations) -> None:  # noqa: ANN001
        c = self.pick([video("Robbery050_x264.mp4", "Robbery")], annotations).candidates[0]
        assert (c.event_type, c.activity) == ("robbery", "Robbery")

    def test_it_is_single_view_and_its_own_source_video(self, annotations) -> None:  # noqa: ANN001
        c = self.pick([video()], annotations).candidates[0]
        assert [v.camera for v in c.views] == ["cam01"] and c.primary_view == "cam01"
        assert c.candidate_id == c.source_video == "ucf_crime:Abuse028_x264"
        assert c.dataset == "ucf_crime"

    def test_the_uri_prefix_is_put_in_front_of_the_path(self, annotations) -> None:  # noqa: ANN001
        c = self.pick([video()], annotations, uri_prefix="s3://b/ucf/").candidates[0]
        assert c.views[0].source_uri == "s3://b/ucf/Videos/Abuse/Abuse028_x264.mp4"

    def test_padding_is_configurable(self, annotations) -> None:  # noqa: ANN001
        c = self.pick(
            [video("Robbery050_x264.mp4", "Robbery")], annotations, pad_before_s=1, pad_after_s=3
        ).candidates[0]
        assert (c.views[0].start_s, c.views[0].end_s) == (0.5, 6.0)  # frames 45-90 are 1.5-3.0 s

    def test_the_eight_default_classes(self) -> None:
        assert DEFAULT_CLASSES == (
            "Abuse",
            "Arrest",
            "Assault",
            "Burglary",
            "Fighting",
            "Robbery",
            "Shoplifting",
            "Vandalism",
        )


class TestCapping:
    def many(self):  # noqa: ANN201
        return [video(f"Abuse{n:03d}_x264.mp4") for n in range(1, 11)] + [
            video(f"Arrest{n:03d}_x264.mp4", "Arrest") for n in range(1, 4)
        ]

    def test_a_cap_per_class(self) -> None:
        sel = select_candidates(self.many(), {}, UcfConfig(per_class_cap=2))
        assert sel.by_class() == {"Abuse": 2, "Arrest": 2}

    def test_a_class_with_fewer_than_the_cap_keeps_all_it_has(self) -> None:
        sel = select_candidates(self.many(), {}, UcfConfig(per_class_cap=5))
        assert sel.by_class() == {"Abuse": 5, "Arrest": 3}

    def test_no_cap_keeps_everything(self) -> None:
        assert (
            len(select_candidates(self.many(), {}, UcfConfig(per_class_cap=None)).candidates) == 13
        )

    def test_the_same_seed_gives_the_same_videos(self) -> None:
        def ids(seed: int) -> list[str]:
            return [
                c.candidate_id
                for c in select_candidates(
                    self.many(), {}, UcfConfig(per_class_cap=3, seed=seed)
                ).candidates
            ]

        assert ids(0) == ids(0)
        assert ids(0) != ids(1)

    def test_the_output_is_in_a_stable_order(self) -> None:
        ids = [
            c.candidate_id
            for c in select_candidates(self.many(), {}, UcfConfig(per_class_cap=None)).candidates
        ]
        assert ids == sorted(ids)


def test_the_summary_lists_each_class_and_what_was_noted() -> None:
    sel = select_candidates(
        [video(duration=0.5), video("Abuse002_x264.mp4")], {}, UcfConfig(per_class_cap=None)
    )
    text = summarise(sel)
    assert "| Abuse | 2 | 1 |" in text and "| **all** | 2 | 1 |" in text
    assert "Noted: 1 too_short" in text


class TestEdgesOfTheFormat:
    def test_a_span_that_starts_at_the_first_frame_is_a_span(self, tmp_path: Path) -> None:
        path = tmp_path / "a.txt"
        path.write_text("Abuse001_x264.mp4 Abuse 0 150 -1 -1\n")
        assert read_temporal_annotations(path)["Abuse001_x264.mp4"][1] == [Span(0.0, 5.0)]

    def test_a_row_with_only_three_fields_is_not_a_row(self, tmp_path: Path) -> None:
        path = tmp_path / "a.txt"
        path.write_text("Abuse001_x264.mp4 Abuse 100\nAbuse002_x264.mp4 Abuse 100 200\n")
        assert list(read_temporal_annotations(path)) == ["Abuse002_x264.mp4"]


class TestEdgesOfTheWindow:
    def pick(self, videos, annotations, **config):  # noqa: ANN001, ANN003, ANN201
        return select_candidates(videos, annotations, UcfConfig(per_class_cap=None, **config))

    def test_a_window_exactly_as_long_as_the_cap_is_not_shortened(self, tmp_path: Path) -> None:
        path = tmp_path / "a.txt"
        path.write_text(
            "Fighting001_x264.mp4 Fighting 300 2100 -1 -1\n"
        )  # 10 s to 70 s, +10 s each side
        sel = self.pick(
            [video("Fighting001_x264.mp4", "Fighting", None)], read_temporal_annotations(path)
        )
        assert (sel.candidates[0].views[0].start_s, sel.candidates[0].views[0].end_s) == (0.0, 80.0)
        sel90 = self.pick(
            [video("Fighting001_x264.mp4", "Fighting", None)],
            read_temporal_annotations(path),
            max_window_s=80.0,
        )
        assert sel90.skipped["window_shortened"] == 0 and sel90.candidates[0].views[0].end_s == 80.0

    def test_a_video_exactly_one_second_long_is_kept_and_a_hair_less_is_not(self) -> None:
        assert len(self.pick([video(duration=1.0)], {}).candidates) == 1
        assert self.pick([video(duration=0.99)], {}).candidates == []


class TestProbing2:
    def fake(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        returncode: int = 0,
        stdout: str = "12.5\n",
        error: Exception | None = None,
    ):  # noqa: ANN202
        monkeypatch.setattr("annotation_kit.ucf.shutil.which", lambda name: "/usr/bin/ffprobe")

        def run(argv, **kwargs):  # noqa: ANN001, ANN003, ANN202
            if error:
                raise error
            return type("R", (), {"returncode": returncode, "stdout": stdout})()

        monkeypatch.setattr("annotation_kit.ucf.subprocess.run", run)

    def test_reads_the_duration_ffprobe_prints(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.fake(monkeypatch)
        assert probe_duration("a.mp4") == 12.5

    def test_a_failing_ffprobe_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.fake(monkeypatch, returncode=1, stdout="12.5\n")
        assert probe_duration("a.mp4") is None

    @pytest.mark.parametrize(
        "error", [OSError("no"), ValueError("bad"), subprocess.TimeoutExpired("x", 1)]
    )
    def test_trouble_running_it_is_none(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception
    ) -> None:
        self.fake(monkeypatch, error=error)
        assert probe_duration("a.mp4") is None

    def test_no_ffprobe_at_all_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("annotation_kit.ucf.shutil.which", lambda name: None)
        assert probe_duration("a.mp4") is None
