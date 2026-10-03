from __future__ import annotations

import json
from pathlib import Path

import pytest
from annotation_kit.cli import main
from annotation_kit.schema import PhavrLabel


def _phase_labels(repo: Path, tmp_path: Path) -> Path:
    clip = " ".join((repo / "ml/annotation/phase_export_example.json").read_text().split())
    path = tmp_path / "phase_labels.jsonl"
    path.write_text(clip + "\n")
    return path


def test_label_config_writes_one_file_per_event_type(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "label-config",
                "--bank",
                str(repo / "config/vqa_bank.yaml"),
                "--out",
                str(tmp_path / "o"),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out.split()
    assert sorted(Path(p).name for p in printed) == [
        "abandoned_object.xml",
        "crowding.xml",
        "default.xml",
        "intrusion.xml",
        "loitering.xml",
        "running.xml",
    ]
    assert all(Path(p).exists() for p in printed)


def test_tasks_expands_clips_and_rewrites_uris_for_the_player(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "tasks.json"
    code = main(
        [
            "tasks",
            str(_phase_labels(repo, tmp_path)),
            "--out",
            str(out),
            "--url-prefix",
            "s3://vms-evidence/=https://media.example/evidence/",
        ]
    )
    assert code == 0
    assert "8 tasks from 1 clips" in capsys.readouterr().out  # 4 phases x 2 views
    tasks = json.loads(out.read_text())
    assert len(tasks) == 8
    first = tasks[0]["data"]
    assert first["view"] == "cam02" and first["phase"] == "baseline"  # the primary view first
    assert first["video"].startswith("https://media.example/evidence/clips/")
    assert first["video"].endswith("#t=0,3.5")
    assert first["video_uri"].startswith("s3://vms-evidence/")


def test_a_malformed_url_prefix_is_refused_with_the_expected_form(
    repo: Path, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit, match="expected FROM=TO"):
        main(
            [
                "tasks",
                str(_phase_labels(repo, tmp_path)),
                "--out",
                str(tmp_path / "t.json"),
                "--url-prefix",
                "nope",
            ]
        )


def test_convert_writes_labels_prints_the_edit_rate_and_can_save_the_report(
    repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bank,  # noqa: ANN001
    make_task,  # noqa: ANN001
    ls_result,  # noqa: ANN001
    answers_for,  # noqa: ANN001
) -> None:
    questions = bank.questions_for("intrusion")
    answers = answers_for(questions)
    export = [
        {
            "data": make_task(phase=phase).model_dump(),
            "annotations": [
                {
                    "id": n,
                    "was_cancelled": False,
                    "completed_by": 1,
                    "result": ls_result(final, answers, "Yes"),
                }
            ],
            "predictions": [
                {"model_version": "m@1", "result": ls_result("A person walks.", answers)}
            ],
        }
        for n, (phase, final) in enumerate(
            [("baseline", "A person walks."), ("precursor", "Someone climbs the gate quickly.")],
            start=1,
        )
    ]
    export.append(
        {"data": make_task(phase="action").model_dump(), "annotations": [], "predictions": []}
    )
    path = tmp_path / "export.json"
    path.write_text(json.dumps(export))
    out, report = tmp_path / "phavr_labels.jsonl", tmp_path / "report.json"

    code = main(
        [
            "convert",
            str(path),
            "--bank",
            str(repo / "config/vqa_bank.yaml"),
            "--out",
            str(out),
            "--report-json",
            str(report),
        ]
    )

    assert code == 0
    text = capsys.readouterr().out
    assert "2 of 3 tasks" in text
    assert "| all | 2 | 2 | 50.0% |" in text  # one of two captions was rewritten
    assert "Skipped: 1 no_annotation" in text
    labels = [PhavrLabel.model_validate_json(line) for line in out.read_text().splitlines()]
    assert [lbl.phase for lbl in labels] == ["baseline", "precursor"]
    saved = json.loads(report.read_text())
    assert saved["overall"]["caption_edit_rate"] == 0.5 and saved["skipped"] == {"no_annotation": 1}


def test_a_subcommand_is_required() -> None:
    with pytest.raises(SystemExit):
        main([])
