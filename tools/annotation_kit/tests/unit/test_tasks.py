from __future__ import annotations

from pathlib import Path

import pytest
from annotation_kit.tasks import (
    dump_json,
    read_phase_labels,
    tasks_from_clips,
    to_label_studio_import,
)


def test_a_clip_makes_one_task_per_phase_per_view(make_clip) -> None:  # noqa: ANN001
    tasks = list(tasks_from_clips([make_clip()]))
    assert len(tasks) == 2 * 2  # 2 phases x 2 views
    assert {(t.phase, t.view) for t in tasks} == {
        ("baseline", "cam02"),
        ("baseline", "cam04"),
        ("precursor", "cam02"),
        ("precursor", "cam04"),
    }


def test_four_phases_in_three_views_make_twelve(make_clip) -> None:  # noqa: ANN001
    clip = make_clip(
        primary_view="cam01",
        views=[{"camera": f"cam0{n}", "video_uri": f"s3://b/{n}.mp4"} for n in (1, 2, 3)],
        phases=[
            {"phase": "baseline", "start_s": 0, "end_s": 2},
            {"phase": "precursor", "start_s": 2, "end_s": 4},
            {"phase": "escalation", "start_s": 4, "end_s": 6},
            {"phase": "action", "start_s": 6, "end_s": 8},
        ],
    )
    assert len(list(tasks_from_clips([clip]))) == 12


def test_the_primary_view_comes_first_within_each_phase(make_clip) -> None:  # noqa: ANN001
    tasks = list(tasks_from_clips([make_clip()]))
    assert [t.view for t in tasks] == ["cam02", "cam04", "cam02", "cam04"]  # cam04 was listed first


def test_phases_stay_in_order(make_clip) -> None:  # noqa: ANN001
    assert [t.phase for t in tasks_from_clips([make_clip()])] == [
        "baseline",
        "baseline",
        "precursor",
        "precursor",
    ]


def test_a_task_carries_the_clip_its_view_and_its_time_span(make_clip) -> None:  # noqa: ANN001
    task = next(t for t in tasks_from_clips([make_clip()]) if t.phase == "precursor")
    assert (task.clip_id, task.source_video, task.event_type) == ("clip-1", "source-1", "intrusion")
    assert (task.start_s, task.end_s) == (3.5, 9)
    assert task.video_uri == "s3://b/clip-1/cam02.mp4"


def test_the_player_url_gets_a_media_fragment_with_the_phases_span(make_clip) -> None:  # noqa: ANN001
    videos = {(t.phase, t.view): t.video for t in tasks_from_clips([make_clip()])}
    assert videos[("precursor", "cam02")] == "s3://b/clip-1/cam02.mp4#t=3.5,9"
    assert videos[("baseline", "cam04")] == "s3://b/clip-1/cam04.mp4#t=0,3.5"


def test_resolving_a_uri_changes_the_player_url_and_not_the_model_one(make_clip) -> None:  # noqa: ANN001
    tasks = list(
        tasks_from_clips([make_clip()], resolve_uri=lambda u: u.replace("s3://b/", "https://m/"))
    )
    assert all(t.video.startswith("https://m/") for t in tasks)
    assert all(t.video_uri.startswith("s3://b/") for t in tasks)


def test_several_clips_are_all_expanded_in_order(make_clip) -> None:  # noqa: ANN001
    tasks = list(tasks_from_clips([make_clip(clip_id="a"), make_clip(clip_id="b")]))
    assert [t.clip_id for t in tasks] == ["a"] * 4 + ["b"] * 4


def test_the_import_format_is_data_only(make_clip) -> None:  # noqa: ANN001
    items = to_label_studio_import(tasks_from_clips([make_clip()]))
    assert set(items[0]) == {"data"}
    assert items[0]["data"]["video"].endswith("#t=0,3.5")  # type: ignore[index]


class TestReadingPhaseLabels:
    def test_reads_one_clip_per_line_and_skips_blank_lines(
        self, tmp_path: Path, repo: Path
    ) -> None:
        clip = (repo / "ml/annotation/phase_export_example.json").read_text()
        one_line = " ".join(clip.split())
        path = tmp_path / "phase_labels.jsonl"
        path.write_text(f"{one_line}\n\n{one_line}\n")
        assert len(read_phase_labels(path)) == 2

    def test_a_bad_line_says_which(self, tmp_path: Path, repo: Path) -> None:
        good = " ".join((repo / "ml/annotation/phase_export_example.json").read_text().split())
        path = tmp_path / "phase_labels.jsonl"
        path.write_text(f'{good}\n{{"clip_id": "x"}}\n')
        with pytest.raises(ValueError, match=r"phase_labels.jsonl, line 2"):
            read_phase_labels(path)


def test_dump_json_writes_readable_utf8(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    dump_json([{"data": {"note": "café"}}], path)
    text = path.read_text(encoding="utf-8")
    assert "café" in text and text.endswith("\n")
