from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from annotation_kit import cli, ucf, ucffetch
from annotation_kit.cli import main

LABELS = (
    "Abuse028_x264.mp4  Abuse  165  240  -1  -1  \n"
    "Arrest024_x264.mp4  Arrest  1005  3105  -1  -1  \n"
    "Burglary005_x264.mp4  Burglary  300  450  600  720  \n"
    "Shooting010_x264.mp4  Shooting  100  200  -1  -1  \n"
    "Normal_Videos_003_x264.mp4  Normal  -1  -1  -1  -1  \n"
)
VIDEOS = {  # path on the mirror -> content
    "Anomaly-Videos-Part-1/Abuse/Abuse028_x264.mp4": b"a" * 10,
    "Anomaly-Videos-Part-1/Abuse/Abuse029_x264.mp4": b"not labelled",
    "Anomaly-Videos-Part-1/Arrest/Arrest024_x264.mp4": b"b" * 20,
    "Anomaly-Videos-Part-2/Burglary/Burglary005_x264.mp4": b"c" * 30,
    "Anomaly-Videos-Part-3/Shooting/Shooting010_x264.mp4": b"d" * 40,
}


def tree_url(path: str) -> str:
    return ucffetch._TREE.format(repo=ucffetch.REPO, path=path)


def resolve_url(path: str) -> str:
    return ucffetch._RESOLVE.format(repo=ucffetch.REPO, path=path)


class Mirror:
    """The mirror's tree API and file server, in memory, with the faults a test asks for."""

    def __init__(self, videos: dict[str, bytes] | None = None) -> None:
        self.files = dict(VIDEOS if videos is None else videos)
        self.files[ucffetch.ANNOTATION_PATH] = LABELS.encode()
        self.opened: list[str] = []
        self.fail_first: dict[str, int] = {}
        self.truncate: set[str] = set()

    def get_json(self, url: str) -> Any:
        listings: dict[str, list[dict[str, Any]]] = {}
        for path, data in self.files.items():
            parts = path.split("/")
            for depth in range(1, len(parts)):
                folder = "/".join(parts[:depth])
                child = "/".join(parts[: depth + 1])
                entry = (
                    {"type": "file", "path": child, "size": len(data)}
                    if depth + 1 == len(parts)
                    else {"type": "directory", "path": child}
                )
                if entry not in listings.setdefault(folder, []):
                    listings[folder].append(entry)
        for folder, entries in listings.items():
            if url == tree_url(folder):
                return entries
        return []  # a part with nothing in it

    def open_url(self, url: str) -> io.BytesIO:
        self.opened.append(url)
        path = next(p for p in self.files if resolve_url(p) == url)
        if self.fail_first.get(path, 0) > 0:
            self.fail_first[path] -= 1
            raise urllib.error.URLError("connection reset")
        data = self.files[path]
        return io.BytesIO(data[:3] if path in self.truncate else data)


@pytest.fixture
def mirror() -> Mirror:
    return Mirror()


def plan_for(mirror: Mirror, classes: tuple[str, ...]) -> ucffetch.Plan:
    labels = {"Abuse028_x264.mp4": ("Abuse", [1]), "Arrest024_x264.mp4": ("Arrest", [1])}
    return ucffetch.plan_downloads(labels, ucffetch.index_videos(mirror.get_json), classes)


class TestIndex:
    def test_finds_every_video_across_the_parts_with_its_class_and_size(self, mirror) -> None:
        index = ucffetch.index_videos(mirror.get_json)
        assert sorted(index) == [
            "Abuse028_x264.mp4", "Abuse029_x264.mp4", "Arrest024_x264.mp4",
            "Burglary005_x264.mp4", "Shooting010_x264.mp4",
        ]  # fmt: skip
        item = index["Burglary005_x264.mp4"]
        assert (item.cls, item.size) == ("Burglary", 30)
        assert item.path == "Anomaly-Videos-Part-2/Burglary/Burglary005_x264.mp4"

    def test_only_videos_with_a_safe_name_in_a_directory_are_taken(self) -> None:
        mirror = Mirror(
            {
                "Anomaly-Videos-Part-1/Abuse/Abuse028_x264.mp4": b"x",
                "Anomaly-Videos-Part-1/Abuse/README.md": b"x",
                "Anomaly-Videos-Part-1/Abuse/notes.txt": b"x",
                "Anomaly-Videos-Part-1/Abuse/bad name!.mp4": b"x",
                "Anomaly-Videos-Part-1/loose.mp4": b"x",
            }
        )
        assert list(ucffetch.index_videos(mirror.get_json)) == ["Abuse028_x264.mp4"]

    def test_a_class_folder_with_an_odd_name_is_not_followed(self) -> None:
        mirror = Mirror(
            {
                "Anomaly-Videos-Part-1/Bad Class/Abuse028_x264.mp4": b"x",
                "Anomaly-Videos-Part-1/Abuse2/Abuse029_x264.mp4": b"x",
                "Anomaly-Videos-Part-1/Abuse/Abuse030_x264.mp4": b"x",
            }
        )
        assert list(ucffetch.index_videos(mirror.get_json)) == ["Abuse030_x264.mp4"]

    def test_a_size_reported_only_under_lfs_is_still_found(self) -> None:
        def get_json(url: str) -> Any:
            if url == tree_url("Anomaly-Videos-Part-1"):
                return [{"type": "directory", "path": "Anomaly-Videos-Part-1/Abuse"}]
            if url == tree_url("Anomaly-Videos-Part-1/Abuse"):
                entry = {"type": "file", "path": "Anomaly-Videos-Part-1/Abuse/Abuse028_x264.mp4"}
                return [{**entry, "lfs": {"size": 99}}]
            return []

        assert ucffetch.index_videos(get_json)["Abuse028_x264.mp4"].size == 99


class TestPlan:
    def test_the_labelled_videos_of_the_wanted_classes_only(self, mirror) -> None:
        plan = plan_for(mirror, ("Abuse",))
        assert [i.name for i in plan.items] == ["Abuse028_x264.mp4"]  # not Abuse029: unlabelled

    def test_classes_are_matched_without_regard_to_case(self, mirror) -> None:
        assert len(plan_for(mirror, ("abuse", "ARREST")).items) == 2

    def test_a_labelled_video_the_mirror_lacks_is_reported_not_skipped_silently(self) -> None:
        index = ucffetch.index_videos(Mirror({}).get_json)
        labels = {"Abuse028_x264.mp4": ("Abuse", [1])}
        plan = ucffetch.plan_downloads(labels, index, ("Abuse",))
        assert plan.items == [] and plan.not_on_mirror == ["Abuse028_x264.mp4"]
        assert "labelled but not on the mirror: Abuse028_x264.mp4" in ucffetch.format_plan(plan)

    def test_totals_and_the_table(self, mirror) -> None:
        plan = plan_for(mirror, ("Abuse", "Arrest"))
        assert plan.bytes == 30 and plan.by_class() == {"Abuse": (1, 10), "Arrest": (1, 20)}
        text = ucffetch.format_plan(plan)
        assert "| Abuse | 1 |" in text and "| **all** | 2 | 0 MB |" in text

    def test_the_plan_is_in_name_order_whatever_order_the_labels_came_in(self, mirror) -> None:
        labels = {"Arrest024_x264.mp4": ("Arrest", [1]), "Abuse028_x264.mp4": ("Abuse", [1])}
        plan = ucffetch.plan_downloads(
            labels, ucffetch.index_videos(mirror.get_json), ("Arrest", "Abuse")
        )
        assert [i.name for i in plan.items] == ["Abuse028_x264.mp4", "Arrest024_x264.mp4"]


class TestAnnotations:
    def test_downloads_and_checks_the_label_file(self, mirror, tmp_path: Path) -> None:
        path = ucffetch.fetch_annotations(tmp_path / "out", mirror.open_url)
        assert path.name == ucffetch.ANNOTATION_FILE and path.read_text() == LABELS
        assert "Abuse028_x264.mp4" in ucf.read_temporal_annotations(path)

    def test_an_empty_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ucffetch.FetchError, match="empty"):
            ucffetch.fetch_annotations(tmp_path, lambda url: io.BytesIO(b"  \n"))

    def test_a_file_this_reader_cannot_read_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ucffetch.FetchError, match="no lines"):
            ucffetch.fetch_annotations(tmp_path, lambda url: io.BytesIO(b"<html>login</html>"))


class TestFetch:
    def test_each_video_lands_under_videos_class_and_leaves_no_part_file(
        self, mirror, tmp_path: Path
    ) -> None:
        report = ucffetch.fetch_videos(
            plan_for(mirror, ("Abuse", "Arrest")), tmp_path, mirror.open_url
        )
        assert (report.downloaded, report.kept, report.failed) == (2, 0, [])
        assert (tmp_path / "Videos/Abuse/Abuse028_x264.mp4").read_bytes() == b"a" * 10
        assert (tmp_path / "Videos/Arrest/Arrest024_x264.mp4").read_bytes() == b"b" * 20
        assert list(tmp_path.rglob("*.part")) == []

    def test_what_is_already_there_with_the_right_size_is_kept_not_fetched_again(
        self, mirror, tmp_path: Path
    ) -> None:
        plan = plan_for(mirror, ("Abuse",))
        ucffetch.fetch_videos(plan, tmp_path, mirror.open_url)
        mirror.opened.clear()
        again = ucffetch.fetch_videos(plan, tmp_path, mirror.open_url)
        assert (again.downloaded, again.kept) == (0, 1) and mirror.opened == []

    def test_a_file_of_the_wrong_size_is_fetched_again(self, mirror, tmp_path: Path) -> None:
        target = tmp_path / "Videos/Abuse/Abuse028_x264.mp4"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"half a vid")  # 10 bytes... make it differ
        target.write_bytes(b"short")
        report = ucffetch.fetch_videos(plan_for(mirror, ("Abuse",)), tmp_path, mirror.open_url)
        assert report.downloaded == 1 and target.read_bytes() == b"a" * 10

    def test_a_dropped_connection_is_retried(self, mirror, tmp_path: Path) -> None:
        mirror.fail_first["Anomaly-Videos-Part-1/Abuse/Abuse028_x264.mp4"] = 2
        report = ucffetch.fetch_videos(plan_for(mirror, ("Abuse",)), tmp_path, mirror.open_url)
        assert report.downloaded == 1 and report.failed == []
        assert len(mirror.opened) == 3

    def test_a_video_that_keeps_failing_is_reported_and_leaves_nothing_behind(
        self, mirror, tmp_path: Path
    ) -> None:
        mirror.fail_first["Anomaly-Videos-Part-1/Abuse/Abuse028_x264.mp4"] = 99
        report = ucffetch.fetch_videos(
            plan_for(mirror, ("Abuse", "Arrest")), tmp_path, mirror.open_url, retries=2
        )
        assert report.failed == ["Abuse028_x264.mp4"] and report.downloaded == 1  # Arrest went on
        assert not (tmp_path / "Videos/Abuse/Abuse028_x264.mp4").exists()
        assert list(tmp_path.rglob("*.part")) == []

    def test_a_truncated_download_is_not_accepted(self, mirror, tmp_path: Path) -> None:
        mirror.truncate.add("Anomaly-Videos-Part-1/Abuse/Abuse028_x264.mp4")
        report = ucffetch.fetch_videos(plan_for(mirror, ("Abuse",)), tmp_path, mirror.open_url)
        assert report.failed == ["Abuse028_x264.mp4"]
        assert not (tmp_path / "Videos/Abuse/Abuse028_x264.mp4").exists()
        assert list(tmp_path.rglob("*.part")) == []  # the half file does not stay

    def test_progress_is_reported_for_every_video_including_the_kept(
        self, mirror, tmp_path: Path
    ) -> None:
        plan = plan_for(mirror, ("Abuse", "Arrest"))
        ucffetch.fetch_videos(plan, tmp_path, mirror.open_url)
        seen: list[tuple[int, int, str]] = []
        ucffetch.fetch_videos(
            plan, tmp_path, mirror.open_url, on_progress=lambda n, t, i: seen.append((n, t, i.name))
        )
        assert seen == [(1, 2, "Abuse028_x264.mp4"), (2, 2, "Arrest024_x264.mp4")]


class TestCommand:
    @pytest.fixture(autouse=True)
    def _patched(self, mirror: Mirror, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli.ucffetch, "http_json", mirror.get_json)
        monkeypatch.setattr(cli.ucffetch, "http_open", mirror.open_url)
        self.mirror = mirror

    def test_a_dry_run_says_what_it_would_fetch_and_fetches_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["ucf-fetch", "--out", str(tmp_path), "--dry-run"])
        out = capsys.readouterr().out
        assert code == 0 and "| Abuse | 1 |" in out and "| Burglary | 1 |" in out
        assert "Shooting" not in out  # not one of the eight by default
        assert not (tmp_path / "Videos").exists()
        assert (tmp_path / ucffetch.ANNOTATION_FILE).exists()

    def test_it_fetches_the_default_eight_and_the_run_can_be_read_by_ucf_candidates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["ucf-fetch", "--out", str(tmp_path)]) == 0
        assert "3 downloaded, 0 already there, 0 failed" in capsys.readouterr().out
        found = ucf.scan_videos(tmp_path / "Videos", ucf.DEFAULT_CLASSES)
        assert sorted(v.name for v in found) == [
            "Abuse028_x264.mp4", "Arrest024_x264.mp4", "Burglary005_x264.mp4",
        ]  # fmt: skip
        out = tmp_path / "c.json"
        code = main([
            "ucf-candidates", "--videos", str(tmp_path / "Videos"),
            "--annotations", str(tmp_path / ucffetch.ANNOTATION_FILE), "--out", str(out),
        ])  # fmt: skip
        assert code == 0 and len(json.loads(out.read_text())) == 3

    def test_other_classes_can_be_asked_for(self, tmp_path: Path) -> None:
        assert main(["ucf-fetch", "--out", str(tmp_path), "--classes", "Shooting"]) == 0
        assert (tmp_path / "Videos/Shooting/Shooting010_x264.mp4").exists()

    def test_a_failed_video_makes_the_exit_code_1_and_is_named(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.mirror.fail_first["Anomaly-Videos-Part-1/Abuse/Abuse028_x264.mp4"] = 99
        assert main(["ucf-fetch", "--out", str(tmp_path)]) == 1
        assert "failed: Abuse028_x264.mp4" in capsys.readouterr().err

    def test_an_unreachable_mirror_is_a_message_not_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def down(url: str) -> io.BytesIO:
            raise urllib.error.URLError("no route")

        monkeypatch.setattr(cli.ucffetch, "http_open", down)
        assert main(["ucf-fetch", "--out", str(tmp_path)]) == 1
        assert capsys.readouterr().err.startswith("ucf-fetch: ")
