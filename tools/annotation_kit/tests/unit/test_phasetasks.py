from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from annotation_kit.candidates import PhaseCandidate, ViewSpec
from annotation_kit.phasetasks import cut_plan, cut_script, phase_task, phase_tasks, run_cuts


def candidate(
    cameras: tuple[str, ...] = ("G420", "G419", "G424"), primary: str = "G419"
) -> PhaseCandidate:
    return PhaseCandidate(
        candidate_id="meva:clip-1:act:7",
        dataset="meva",
        source_video="meva:3-420:slot",
        event_type="activity",
        activity="vehicle_drops_off_person",
        primary_view=primary,
        views=[
            ViewSpec(camera=c, source_uri=f"s3://src/{c}.avi", start_s=10 + i, end_s=50 + i)
            for i, c in enumerate(cameras)
        ],
    )


PREFIX = "s3://vms-evidence/clips"


class TestATask:
    def test_carries_what_the_converter_needs_to_rebuild_a_label(self) -> None:
        data = phase_task(candidate(), clip_prefix=PREFIX)["data"]
        assert data["candidate_id"] == "meva:clip-1:act:7"
        assert (data["dataset"], data["source_video"], data["event_type"]) == (
            "meva",
            "meva:3-420:slot",
            "activity",
        )
        assert data["activity"] == "vehicle_drops_off_person"
        assert data["duration_s"] == 40.0
        assert data["primary_view"] == "G419"

    def test_the_primary_view_comes_first_and_the_rest_in_camera_order(self) -> None:
        data = phase_task(candidate(), clip_prefix=PREFIX)["data"]
        assert data["views"] == ["G419", "G420", "G424"]
        assert data["view_choices"] == [{"value": c} for c in ("G419", "G420", "G424")]
        assert [c["camera"] for c in data["clips"]] == ["G419", "G420", "G424"]

    def test_the_players_videos_are_the_cut_clips_in_that_order(self) -> None:
        data = phase_task(candidate(), clip_prefix=PREFIX)["data"]
        base = f"{PREFIX}/meva_clip-1_act_7"
        assert data["video"] == f"{base}/G419.mp4"
        assert (data["video_2"], data["video_3"]) == (f"{base}/G420.mp4", f"{base}/G424.mp4")
        assert "video_4" not in data

    def test_the_stored_uris_are_untouched_and_only_the_players_ones_are_resolved(self) -> None:
        data = phase_task(
            candidate(),
            clip_prefix=PREFIX,
            resolve_uri=lambda u: u.replace("s3://vms-evidence/", "https://m/"),
        )["data"]
        assert data["video"].startswith("https://m/clips/")
        assert all(c["video_uri"].startswith("s3://vms-evidence/clips/") for c in data["clips"])

    def test_a_single_view_task_has_only_video(self) -> None:
        data = phase_task(candidate(("cam01",), "cam01"), clip_prefix=PREFIX)["data"]
        assert data["views"] == ["cam01"] and "video_2" not in data

    def test_a_candidate_with_no_activity_has_an_empty_one(self) -> None:
        c = candidate().model_copy(update={"activity": None})
        assert phase_task(c, clip_prefix=PREFIX)["data"]["activity"] == ""


def test_tasks_are_grouped_by_how_many_views_they_have() -> None:
    grouped = phase_tasks(
        [
            candidate(),
            candidate(("cam01",), "cam01").model_copy(update={"candidate_id": "u:1"}),
            candidate(("a", "b"), "a").model_copy(update={"candidate_id": "x:2"}),
        ],
        clip_prefix=PREFIX,
    )
    assert list(grouped) == [1, 2, 3]  # in order of view count
    assert [len(v) for v in grouped.values()] == [1, 1, 1]


class TestCutting:
    def test_a_cut_for_every_view_of_every_candidate_under_its_own_folder(
        self, tmp_path: Path
    ) -> None:
        plan = cut_plan([candidate()], tmp_path)
        assert [p for p, _ in plan] == [
            tmp_path / "meva_clip-1_act_7" / f"{c}.mp4" for c in ("G420", "G419", "G424")
        ]
        for path, argv in plan:
            assert argv[0] == "ffmpeg" and argv[-1] == str(path)

    def test_the_source_can_be_pointed_at_a_local_copy(self, tmp_path: Path) -> None:
        plan = cut_plan(
            [candidate()], tmp_path, resolve_source=lambda u: u.replace("s3://src/", "/data/")
        )
        assert plan[0][1][plan[0][1].index("-i") + 1] == "/data/G420.avi"

    def test_each_view_is_cut_at_its_own_start(self, tmp_path: Path) -> None:
        starts = [argv[argv.index("-ss") + 1] for _p, argv in cut_plan([candidate()], tmp_path)]
        assert starts == ["10.000", "11.000", "12.000"]

    def test_the_script_makes_the_folders_and_skips_clips_that_exist(self, tmp_path: Path) -> None:
        script = cut_script(cut_plan([candidate(("cam01",), "cam01")], tmp_path))
        assert script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
        assert f"mkdir -p {tmp_path}/meva_clip-1_act_7" in script
        assert "[ -s " in script and "|| ffmpeg" in script

    def test_paths_with_spaces_are_quoted(self, tmp_path: Path) -> None:
        script = cut_script(cut_plan([candidate(("cam01",), "cam01")], tmp_path / "my clips"))
        assert "'" + str(tmp_path / "my clips") in script


class TestRunningTheCuts:
    def plan(self, tmp_path: Path):  # noqa: ANN201
        return cut_plan([candidate()], tmp_path)

    def runner(self, fail: set[str] = frozenset()):  # noqa: ANN201
        calls: list[list[str]] = []

        def run(argv, check=False):  # noqa: ANN001, ANN202
            calls.append(argv)
            out = Path(argv[-1])
            if out.name.split(".")[0] in fail:
                return SimpleNamespace(returncode=1)
            out.write_bytes(b"video")
            return SimpleNamespace(returncode=0)

        run.calls = calls  # type: ignore[attr-defined]
        return run

    def test_cuts_what_is_missing(self, tmp_path: Path) -> None:
        run = self.runner()
        assert run_cuts(self.plan(tmp_path), run=run) == {"cut": 3, "kept": 0, "failed": 0}
        assert len(run.calls) == 3

    def test_keeps_what_is_already_there_and_does_not_cut_it_again(self, tmp_path: Path) -> None:
        run = self.runner()
        run_cuts(self.plan(tmp_path), run=run)
        run.calls.clear()
        assert run_cuts(self.plan(tmp_path), run=run) == {"cut": 0, "kept": 3, "failed": 0}
        assert run.calls == []

    def test_an_empty_file_left_by_a_crash_is_cut_again(self, tmp_path: Path) -> None:
        plan = self.plan(tmp_path)
        plan[0][0].parent.mkdir(parents=True)
        plan[0][0].write_bytes(b"")
        done = run_cuts(plan, run=self.runner())
        assert done == {"cut": 3, "kept": 0, "failed": 0}

    def test_a_failed_cut_is_counted_and_leaves_nothing_behind(self, tmp_path: Path) -> None:
        plan = self.plan(tmp_path)
        done = run_cuts(plan, run=self.runner(fail={"G419"}))
        assert done == {"cut": 2, "kept": 0, "failed": 1}
        assert not plan[1][0].exists()

    def test_a_success_that_wrote_nothing_counts_as_a_failure(self, tmp_path: Path) -> None:
        plan = self.plan(tmp_path)
        done = run_cuts(plan, run=lambda argv, check=False: SimpleNamespace(returncode=0))
        assert done["failed"] == 3 and done["cut"] == 0


class TestAFailedCutLeavesNothing:
    def test_a_partial_file_from_a_failed_ffmpeg_is_removed(self, tmp_path: Path) -> None:
        plan = cut_plan([candidate(("cam01",), "cam01")], tmp_path)

        def run(argv, check=False):  # noqa: ANN001, ANN202
            Path(argv[-1]).write_bytes(b"half a video")  # ffmpeg died after writing something
            return SimpleNamespace(returncode=1)

        assert run_cuts(plan, run=run) == {"cut": 0, "kept": 0, "failed": 1}
        assert not plan[0][0].exists()
