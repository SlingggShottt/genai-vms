"""The Kaggle pre-annotation notebook, run for real with the placeholder model.

Everything except the model call is the notebook's own code: loading the bank and the clips,
expanding tasks, prompting, reading replies, checkpointing and resuming, handling a clip that fails.
Qwen2.5-VL-7B itself is not run here (it needs a GPU); `FAKE_MODEL` stands in for it.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from annotation_kit.convert import convert
from annotation_kit.labelconfig import USABLE
from annotation_kit.report import edit_report
from vms_common.vqa_bank import VQABank

NOTEBOOK = "ml/annotation/caption_vqa/prelabel_kaggle.ipynb"


@pytest.fixture
def cells(repo: Path) -> list[str]:
    notebook = json.loads((repo / NOTEBOOK).read_text())
    return ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]


@pytest.fixture
def run(
    cells: list[str], repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., dict[str, Any]]:
    clip = " ".join((repo / "ml/annotation/phase_export_example.json").read_text().split())
    phase_labels = tmp_path / "phase_labels.jsonl"
    phase_labels.write_text(clip + "\n")
    monkeypatch.setattr(sys, "path", list(sys.path))  # the setup cell edits it
    for name, value in {
        "ANNOTATION_REPO_DIR": str(repo),
        "PHASE_LABELS": str(phase_labels),
        "OUT_DIR": str(tmp_path / "out"),
        "FAKE_MODEL": "1",
    }.items():
        monkeypatch.setenv(name, value)

    def go(
        *, start: int = 0, upto: int | None = None, namespace: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run code cells `start` up to (not including) `upto`, in `namespace`."""
        ns: dict[str, Any] = namespace if namespace is not None else {}
        for number, source in enumerate(cells):
            if number < start or (upto is not None and number >= upto):
                continue
            exec(compile(source, f"<cell {number}>", "exec"), ns)  # noqa: S102 - our own notebook
        return ns

    return go


def test_every_code_cell_compiles(cells: list[str]) -> None:
    assert len(cells) == 6
    for number, source in enumerate(cells):
        compile(source, f"<cell {number}>", "exec")


def test_the_example_clip_becomes_eight_drafted_tasks(run, tmp_path: Path, bank: VQABank) -> None:  # noqa: ANN001
    ns = run()
    items = json.loads((tmp_path / "out/preannotated_tasks.json").read_text())
    assert len(items) == 8  # 4 phases x 2 views
    assert ns["MODEL_VERSION"] == "fake-model@prelabel/1.0"
    assert all(len(item["predictions"]) == 1 for item in items)
    questions = bank.questions_for("intrusion")
    for item in items:
        result = item["predictions"][0]["result"]
        assert [r["from_name"] for r in result] == ["caption", *[q.id for q in questions]]
        assert item["predictions"][0]["model_version"] == "fake-model@prelabel/1.0"
    stats = ns["stats"]
    assert (stats.tasks, stats.unparseable, stats.coerced_answers) == (8, 0, 0)


def test_the_primary_view_is_drafted_first_within_each_phase(run, tmp_path: Path) -> None:  # noqa: ANN001
    run()
    items = json.loads((tmp_path / "out/preannotated_tasks.json").read_text())
    assert [i["data"]["view"] for i in items[:4]] == ["cam02", "cam04", "cam02", "cam04"]


def test_the_whole_pipeline_from_clip_to_edit_rate(
    run, tmp_path: Path, bank: VQABank, ls_result
) -> None:  # noqa: ANN001
    """Draft -> an annotator accepts every draft unchanged -> convert -> nothing was edited."""
    run()
    export = []
    for number, item in enumerate(
        json.loads((tmp_path / "out/preannotated_tasks.json").read_text())
    ):
        draft = item["predictions"][0]["result"]
        caption = draft[0]["value"]["text"][0]
        answers = {r["from_name"]: r["value"]["choices"][0] for r in draft[1:]}
        export.append(
            {
                **item,
                "annotations": [
                    {
                        "id": number + 1,
                        "was_cancelled": False,
                        "completed_by": 1,
                        "result": ls_result(caption, answers, "Yes"),
                    }
                ],
            }
        )
    converted = convert(export, bank)
    assert len(converted.labels) == 8 and not any(converted.skipped.values())
    report = edit_report(converted.labels)
    assert report.overall.drafted == 8
    assert report.overall.caption_edit_rate == 0.0
    assert report.overall.answer_change_rate == 0.0
    assert report.overall.untouched_rate == 1.0
    assert USABLE  # the control the converter relies on exists


def test_a_second_run_resumes_and_does_not_redraft(run, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    run()
    out = tmp_path / "out/preannotated_tasks.json"
    first = out.read_text()
    capsys.readouterr()
    ns = run()
    assert "8 already done, 0 to do" in capsys.readouterr().out
    assert out.read_text() == first
    assert ns["stats"].tasks == 0


def test_a_partial_file_is_completed_not_restarted(run, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    run()
    out = tmp_path / "out/preannotated_tasks.json"
    full = json.loads(out.read_text())
    out.write_text(json.dumps(full[:3]))
    capsys.readouterr()
    ns = run()
    assert "3 already done, 5 to do" in capsys.readouterr().out
    assert [i["data"] for i in json.loads(out.read_text())] == [i["data"] for i in full]
    assert ns["stats"].tasks == 5


def test_limit_labels_only_the_first_tasks(
    run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    monkeypatch.setenv("LIMIT", "3")
    run()
    assert len(json.loads((tmp_path / "out/preannotated_tasks.json").read_text())) == 3


def test_a_clip_that_fails_is_recorded_and_left_blank_without_stopping_the_run(
    run,
    tmp_path: Path,
    capsys,  # noqa: ANN001
) -> None:
    ns = run(upto=4)  # setup, config, load the tasks, build the (fake) model: nothing drafted yet
    placeholder = ns["labeler"]

    def flaky(task: Any, prompt: str) -> str:
        if task.view == "cam04" and task.phase == "action":
            raise FileNotFoundError("/kaggle/input/missing/cam04.mp4")
        return placeholder(task, prompt)

    ns["labeler"] = flaky
    run(start=4, namespace=ns)  # draft, then summarise

    items = json.loads((tmp_path / "out/preannotated_tasks.json").read_text())
    assert len(items) == 8  # the failure did not stop the run or drop the task
    blank = [(i["data"]["view"], i["data"]["phase"]) for i in items if not i["predictions"]]
    assert blank == [("cam04", "action")]  # that task has no draft: the annotator starts blank
    assert ns["failures"] == [
        (
            "meva-2018-03-05-16-30-school-g421|cam04|action",
            "FileNotFoundError('/kaggle/input/missing/cam04.mp4')",
        )
    ]
    out = capsys.readouterr().out
    assert "FAILED meva-2018-03-05-16-30-school-g421|cam04|action" in out
    assert "replies with no usable JSON (annotator starts blank): 1" in out


def test_a_clips_storage_uri_is_mapped_to_where_the_videos_were_uploaded(run, make_task) -> None:  # noqa: ANN001
    ns = run(upto=4)
    local = ns["local_path"]
    ns["URI_PREFIX"], ns["VIDEO_ROOT"] = "s3://vms-evidence/", "/kaggle/input/clips/"
    assert (
        local(make_task(video_uri="s3://vms-evidence/clips/c1/cam02.mp4"))
        == "/kaggle/input/clips/clips/c1/cam02.mp4"
    )
    # a uri that is not under the prefix is already a path: left alone
    assert local(make_task(video_uri="/data/c1/cam02.mp4")) == "/data/c1/cam02.mp4"


def test_the_placeholder_run_never_imports_the_model_libraries(run) -> None:  # noqa: ANN001
    before = set(sys.modules)
    run()
    imported = set(sys.modules) - before
    assert not {
        m for m in imported if m.split(".")[0] in {"torch", "transformers", "cv2", "qwen_vl_utils"}
    }
