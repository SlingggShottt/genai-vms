from __future__ import annotations

import json
from pathlib import Path

import pytest
from annotation_kit import cli
from annotation_kit.candidates import read_candidates
from annotation_kit.cli import _event_types, main
from annotation_kit.phaseconfig import write_phase_configs
from annotation_kit.schema import PhaseLabelClip
from annotation_kit.tasks import read_phase_labels

A = "2018-03-05.09-50-00.09-55-00.school.G420"
B = "2018-03-05.09-50-00.09-55-00.school.G419"
SLOT = "2018-03-05.09-50-00"


def meva_repo(tmp_path: Path) -> Path:
    (tmp_path / "metadata").mkdir(exist_ok=True)
    (tmp_path / "metadata/meva-clip-camera-and-time-table.txt").write_text(
        f"{A} {SLOT} x 3-420 self 0 0\n{B} {SLOT} x 3-420 {A} 120 30\n"
    )
    folder = tmp_path / "annotation/DIVA-phase-2/MEVA/kitware/2018-03-05/09"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{A}.activities.yml").write_text(
        "- {act: {act2: {vehicle_drops_off_person: 1.0}, id2: 1, "
        "timespan: [{tsr0: [3000, 3600]}], src_status: good, actors: [{id1: 1}]}}\n"
        "- {act: {act2: {person_embraces_person: 1.0}, id2: 2, "
        "timespan: [{tsr0: [5000, 5200]}], src_status: good, actors: [{id1: 1}]}}\n"
    )
    return tmp_path


def test_phase_config_writes_the_four_configs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["phase-config", "--out", str(tmp_path / "o")]) == 0
    names = sorted(Path(p).name for p in capsys.readouterr().out.split())
    assert names == [f"phase_labelling_{n}.xml" for n in ("1view", "2views", "3views", "4views")]


class TestMevaCandidates:
    def test_writes_candidates_and_prints_what_it_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "candidates.json"
        assert main(["meva-candidates", "--repo", str(meva_repo(tmp_path)), "--out", str(out)]) == 0
        text = capsys.readouterr().out
        candidates = read_candidates(out)
        assert len(candidates) == 2 and {c.activity for c in candidates} == {
            "vehicle_drops_off_person",
            "person_embraces_person",
        }
        assert all(len(c.views) == 2 for c in candidates)
        assert "2 candidates" in text and "| vehicle_drops_off_person | 1 | 1 |" in text

    def test_choosing_activities_and_padding(self, tmp_path: Path) -> None:
        out = tmp_path / "c.json"
        main(
            [
                "meva-candidates",
                "--repo",
                str(meva_repo(tmp_path)),
                "--out",
                str(out),
                "--activity",
                "person_embraces_person",
                "--pad-before",
                "2",
                "--pad-after",
                "2",
            ]
        )
        (candidate,) = read_candidates(out)
        assert candidate.activity == "person_embraces_person"
        assert candidate.duration_s == pytest.approx(200 / 30 + 4)

    def test_min_views_is_respected(self, tmp_path: Path) -> None:
        out = tmp_path / "c.json"
        main(
            [
                "meva-candidates",
                "--repo",
                str(meva_repo(tmp_path)),
                "--out",
                str(out),
                "--min-views",
                "3",
            ]
        )
        assert read_candidates(out) == []

    def test_a_cap_of_zero_means_no_cap(self) -> None:
        assert cli._cap(0) is None and cli._cap(-1) is None and cli._cap(5) == 5


class TestUcfCandidates:
    def dataset(self, tmp_path: Path) -> tuple[Path, Path]:
        for n in (1, 2, 3):
            folder = tmp_path / "ucf/Videos/Fighting"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"Fighting{n:03d}_x264.mp4").write_bytes(b"")
        (tmp_path / "ucf/Videos/Arson").mkdir(parents=True)
        (tmp_path / "ucf/Videos/Arson/Arson001_x264.mp4").write_bytes(b"")
        annotations = tmp_path / "ann.txt"
        annotations.write_text("Fighting002_x264.mp4 Fighting 300 600 -1 -1\n")
        return tmp_path / "ucf", annotations

    def test_writes_candidates_for_the_chosen_classes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        videos, annotations = self.dataset(tmp_path)
        out = tmp_path / "c.json"
        code = main(
            [
                "ucf-candidates",
                "--videos",
                str(videos),
                "--annotations",
                str(annotations),
                "--out",
                str(out),
                "--uri-prefix",
                "s3://b/ucf/",
            ]
        )
        candidates = read_candidates(out)
        assert code == 0 and len(candidates) == 3  # Arson is not one of the default classes
        assert {c.event_type for c in candidates} == {"fighting"}
        located = next(c for c in candidates if c.candidate_id.endswith("Fighting002_x264"))
        assert located.note == "around the annotated anomaly" and located.views[0].start_s == 0.0
        assert located.views[0].source_uri == "s3://b/ucf/Videos/Fighting/Fighting002_x264.mp4"
        assert "| Fighting | 3 | 3 |" in capsys.readouterr().out

    def test_works_without_an_annotation_file(self, tmp_path: Path) -> None:
        videos, _ = self.dataset(tmp_path)
        out = tmp_path / "c.json"
        assert main(["ucf-candidates", "--videos", str(videos), "--out", str(out)]) == 0
        assert all(c.note == "untrimmed: anomaly not located" for c in read_candidates(out))

    def test_choosing_classes_and_a_cap(self, tmp_path: Path) -> None:
        videos, _ = self.dataset(tmp_path)
        out = tmp_path / "c.json"
        main(
            [
                "ucf-candidates",
                "--videos",
                str(videos),
                "--out",
                str(out),
                "--classes",
                "Fighting",
                "--per-class-cap",
                "2",
            ]
        )
        assert len(read_candidates(out)) == 2


class TestFromCandidatesToTasksAndCuts:
    def candidates(self, tmp_path: Path) -> Path:
        out = tmp_path / "candidates.json"
        main(["meva-candidates", "--repo", str(meva_repo(tmp_path)), "--out", str(out)])
        return out

    def test_phase_tasks_writes_one_file_per_number_of_views_and_names_the_config(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        candidates = self.candidates(tmp_path)
        capsys.readouterr()
        code = main(
            [
                "phase-tasks",
                str(candidates),
                "--clip-prefix",
                "s3://vms/clips",
                "--out-dir",
                str(tmp_path / "t"),
                "--url-prefix",
                "s3://vms/=https://media.example/",
            ]
        )
        assert code == 0
        tasks = json.loads((tmp_path / "t/tasks_2views.json").read_text())
        assert len(tasks) == 2
        assert tasks[0]["data"]["video"].startswith("https://media.example/clips/")
        assert tasks[0]["data"]["clips"][0]["video_uri"].startswith("s3://vms/clips/")
        assert "config: phase_labelling_2views.xml" in capsys.readouterr().out

    def test_cut_writes_a_script_by_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        candidates = self.candidates(tmp_path)
        capsys.readouterr()
        script = tmp_path / "cut.sh"
        code = main(
            [
                "cut",
                str(candidates),
                "--out-dir",
                str(tmp_path / "clips"),
                "--script",
                str(script),
                "--source-prefix",
                "s3://mevadata-public-01/=/data/meva/",
            ]
        )
        text = script.read_text()
        assert code == 0 and "4 cuts" in capsys.readouterr().out  # 2 candidates x 2 views
        assert "-i /data/meva/drops-123-r13/2018-03-05/09/" in text and "s3://" not in text

    def test_cut_run_reports_and_fails_loudly_if_a_cut_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        candidates = self.candidates(tmp_path)
        monkeypatch.setattr(cli, "run_cuts", lambda plan: {"cut": 3, "kept": 0, "failed": 1})
        assert main(["cut", str(candidates), "--out-dir", str(tmp_path / "c"), "--run"]) == 1
        assert "cut 3, kept 0, failed 1 of 4" in capsys.readouterr().out
        monkeypatch.setattr(cli, "run_cuts", lambda plan: {"cut": 4, "kept": 0, "failed": 0})
        assert main(["cut", str(candidates), "--out-dir", str(tmp_path / "c"), "--run"]) == 0

    def test_a_bad_source_prefix_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="expected FROM=TO"):
            main(
                ["cut", str(self.candidates(tmp_path)), "--out-dir", "x", "--source-prefix", "nope"]
            )


class TestFromAnExportToLabelsToAgreement:
    def export(self, tmp_path: Path, spans: tuple[tuple[str, int, int], ...]) -> Path:
        out = tmp_path / "candidates.json"
        main(
            [
                "meva-candidates",
                "--repo",
                str(meva_repo(tmp_path)),
                "--out",
                str(out),
                "--activity",
                "vehicle_drops_off_person",
            ]
        )
        tasks_dir = tmp_path / "t"
        main(
            [
                "phase-tasks",
                str(out),
                "--clip-prefix",
                "s3://vms/clips",
                "--out-dir",
                str(tasks_dir),
            ]
        )
        (task,) = json.loads((tasks_dir / "tasks_2views.json").read_text())
        rate = task["data"]["timeline_fps"]  # `spans` are frames at 30 fps; Label Studio counts
        results = [  # frames at this rate, from 1, the last one included
            {
                "from_name": "phase",
                "to_name": "video",
                "type": "timelinelabels",
                "value": {
                    "ranges": [{"start": round(s / 30 * rate) + 1, "end": round(e / 30 * rate)}],
                    "timelinelabels": [p],
                },
            }
            for p, s, e in spans
        ]
        task["annotations"] = [{"id": 1, "was_cancelled": False, "result": results}]
        path = tmp_path / f"export_{len(spans)}_{spans[0][1]}.json"
        path.write_text(json.dumps([task]))
        return path

    def test_convert_writes_phase_labels_the_caption_kit_can_read(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        export = self.export(tmp_path, (("baseline", 0, 300), ("action", 300, 900)))
        out = tmp_path / "phase_labels.jsonl"
        assert main(["phase-convert", str(export), "--out", str(out)]) == 0
        assert "1 of 1 tasks became phase labels." in capsys.readouterr().out
        (clip,) = read_phase_labels(out)
        assert isinstance(clip, PhaseLabelClip) and [p.phase for p in clip.phases] == [
            "baseline",
            "action",
        ]
        # ... and the caption/VQA kit expands it: 2 phases x 2 views
        assert main(["tasks", str(out), "--out", str(tmp_path / "caption_tasks.json")]) == 0
        assert len(json.loads((tmp_path / "caption_tasks.json").read_text())) == 4

    def test_agreement_between_two_annotators(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        main(
            [
                "phase-convert",
                str(self.export(tmp_path, (("baseline", 0, 300), ("action", 300, 900)))),
                "--out",
                str(first),
            ]
        )
        main(
            [
                "phase-convert",
                str(
                    self.export(
                        tmp_path,
                        (("baseline", 0, 360), ("action", 360, 900), ("aftermath", 900, 960)),
                    )
                ),
                "--out",
                str(second),
            ]
        )
        capsys.readouterr()
        report = tmp_path / "agreement.json"
        assert main(["phase-agreement", str(first), str(second), "--report-json", str(report)]) == 0
        text = capsys.readouterr().out
        assert (
            "Clips both annotated: 1" in text
            and "WARNING: the overlap set should have 20 clips" in text
        )
        assert "| aftermath | 0.0% | 0.0% |" in text
        saved = json.loads(report.read_text())
        assert saved["clips"] == 1 and 0 < saved["miou"] < 1


def test_probe_reads_each_videos_length_and_the_window_stops_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "ucf/Videos/Fighting"
    folder.mkdir(parents=True)
    (folder / "Fighting001_x264.mp4").write_bytes(b"")
    monkeypatch.setattr(cli.ucf, "probe_duration", lambda path: 10.0)
    probed, plain = tmp_path / "probed.json", tmp_path / "plain.json"
    main(["ucf-candidates", "--videos", str(tmp_path / "ucf"), "--out", str(probed), "--probe"])
    main(["ucf-candidates", "--videos", str(tmp_path / "ucf"), "--out", str(plain)])
    assert read_candidates(probed)[0].views[0].end_s == 10.0
    assert read_candidates(plain)[0].views[0].end_s == 90.0


class TestThePhaseConfigsTheCommandWrites:
    def test_the_default_list_is_the_bank_then_meva_then_ucf_classes_without_repeats(
        self, repo: Path
    ) -> None:
        types = _event_types(str(repo / "config/vqa_bank.yaml"))
        assert types[:5] == ["intrusion", "loitering", "crowding", "abandoned_object", "running"]
        assert "default" not in types
        assert {"theft", "activity", "abuse", "arrest", "assault", "burglary"} <= set(types)
        assert len(set(types)) == len(types) == 15

    def test_the_committed_configs_are_what_phase_config_writes(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """After changing the phases or event types: `annotation-kit phase-config --out ...`."""
        generated = write_phase_configs(_event_types(str(repo / "config/vqa_bank.yaml")), tmp_path)
        committed = repo / "ml/annotation/phase"
        assert sorted(p.name for p in committed.glob("*.xml")) == sorted(p.name for p in generated)
        for path in generated:
            assert (committed / path.name).read_text() == path.read_text(), path.name
