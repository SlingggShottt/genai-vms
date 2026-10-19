from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from annotation_kit import cli, labelstudio
from annotation_kit.cli import main
from annotation_kit.draftedits import stages as read_stages
from annotation_kit.phases import PHASES

STAGES = [["baseline", 0, 10], ["action", 10, 14], ["aftermath", 14, 24]]


class TestTheResultOfADraft:
    def result(self, stages=STAGES, frames=24, fps=1, view="cam01", event="robbery"):  # noqa: ANN001, ANN201
        return labelstudio.draft_result(
            stages, frames=frames, fps=fps, primary_view=view, event_type=event
        )

    def test_seconds_become_label_studios_frames_counted_from_one_with_the_last_included(
        self,
    ) -> None:
        marks = read_stages(self.result())
        assert marks == {"baseline": (1, 10), "action": (11, 14), "aftermath": (15, 24)}

    def test_at_another_rate_a_second_is_that_many_frames(self) -> None:
        marks = read_stages(self.result([["action", 2, 5]], frames=40, fps=2))
        assert marks == {"action": (5, 10)}

    def test_the_last_stage_is_cut_to_the_clip(self) -> None:
        assert read_stages(self.result([["action", 10, 30]], frames=24)) == {"action": (11, 24)}

    def test_the_three_answers_are_filled_in(self) -> None:
        answers = {
            r["from_name"]: r["value"]["choices"][0]
            for r in self.result()
            if r["type"] == "choices"
        }
        assert answers == {"primary_view": "cam01", "event_type": "robbery", "usable": "Yes"}

    @pytest.mark.parametrize(
        "bad",
        [
            [["baseline", 0, 10], ["baseline", 12, 14]],  # twice
            [["action", 10, 14], ["baseline", 0, 10]],  # out of order
            [["action", 0, 10], ["aftermath", 8, 12]],  # overlapping
            [["escalating", 0, 4]],  # not a stage
            [["action", 24, 30]],  # nothing of it inside a 24 frame clip
        ],
    )
    def test_refuses_what_could_not_be_a_valid_mark(self, bad: list) -> None:
        with pytest.raises(labelstudio.LabelStudioError):
            self.result(bad)

    def test_touching_stages_are_fine(self) -> None:
        marks = read_stages(self.result([["baseline", 0, 10], ["action", 10, 14]]))
        assert marks["baseline"][1] + 1 == marks["action"][0]

    def test_the_stage_names_are_the_kits(self) -> None:
        assert labelstudio.STAGES == PHASES


class FakeServer:
    """The few endpoints add_drafts uses, with the predictions it was sent."""

    def __init__(self) -> None:
        self.projects = {
            1: {"id": 1, "title": "divyansh - 1 view", "model_version": ""},
            2: {"id": 2, "title": "divyansh - 2 views", "model_version": ""},
            3: {"id": 3, "title": "someone else - 1 view", "model_version": ""},
        }
        self.tasks = {
            10: (
                1,
                {
                    "candidate_id": "ucf_crime:A",
                    "duration_s": 24.4,
                    "primary_view": "cam01",
                    "event_type": "robbery",
                    "timeline_fps": 1,
                },
            ),
            11: (
                2,
                {
                    "candidate_id": "meva:B",
                    "duration_s": 30.0,
                    "primary_view": "G1",
                    "event_type": "activity",
                    "timeline_fps": 1,
                },
            ),
            12: (
                3,
                {
                    "candidate_id": "ucf_crime:Z",
                    "duration_s": 20.0,
                    "primary_view": "cam01",
                    "event_type": "arrest",
                    "timeline_fps": 1,
                },
            ),
        }
        self.predictions: list[dict[str, Any]] = []
        self.patched: list[tuple[int, dict]] = []

    def __call__(self, method: str, path: str, payload: Any = None) -> Any:
        if (method, path.split("?")[0]) == ("GET", "/api/projects"):
            return {"results": list(self.projects.values())}
        if method == "GET" and path.startswith("/api/tasks?project="):
            pid = int(path.split("project=")[1].split("&")[0])
            return {"tasks": [{"id": t, "data": d} for t, (p, d) in self.tasks.items() if p == pid]}
        if method == "GET" and path.startswith("/api/predictions?task="):
            task = int(path.split("=")[1])
            return [p for p in self.predictions if p["task"] == task]
        if (method, path) == ("POST", "/api/predictions"):
            self.predictions.append(payload)
            return payload
        if method == "PATCH" and path.startswith("/api/projects/"):
            self.patched.append((int(path.rsplit("/", 1)[1]), payload))
            return payload
        raise AssertionError(f"unexpected {method} {path}")


DRAFTS = [
    {"candidate_id": "ucf_crime:A", "confidence": "seen", "stages": STAGES},
    {
        "candidate_id": "meva:B",
        "confidence": "prior",
        "stages": [["baseline", 0, 10], ["action", 10, 20]],
    },
]


class TestAddDrafts:
    def test_each_draft_goes_to_its_task_with_the_clips_own_answers(self) -> None:
        fake = FakeServer()
        report = labelstudio.add_drafts(fake, "divyansh", DRAFTS, model_version="v1")
        assert (report["added"], report["already_there"], report["no_task"]) == (2, 0, [])
        by_task = {p["task"]: p for p in fake.predictions}
        assert set(by_task) == {10, 11} and all(
            p["model_version"] == "v1" for p in by_task.values()
        )
        assert read_stages(by_task[10]["result"]) == {
            "baseline": (1, 10),
            "action": (11, 14),
            "aftermath": (15, 24),
        }  # 24.4 s -> 24 frames
        events = {
            t: [r["value"]["choices"][0] for r in p["result"] if r["from_name"] == "event_type"][0]
            for t, p in by_task.items()
        }
        assert events == {10: "robbery", 11: "activity"}

    def test_a_draft_for_someone_elses_clip_is_not_loaded(self) -> None:
        fake = FakeServer()
        report = labelstudio.add_drafts(
            fake,
            "divyansh",
            [{"candidate_id": "ucf_crime:Z", "stages": STAGES}],
            model_version="v1",
        )
        assert (
            report["no_task"] == ["ucf_crime:Z"] and fake.predictions == [] and fake.patched == []
        )

    def test_a_clip_of_24_point_6_seconds_has_24_frames_not_25(self) -> None:
        fake = FakeServer()
        fake.tasks[10][1]["duration_s"] = 24.6  # Label Studio counts whole seconds, rounding down
        draft = {"candidate_id": "ucf_crime:A", "stages": [["aftermath", 14, 40]]}
        labelstudio.add_drafts(fake, "divyansh", [draft], model_version="v1")
        assert read_stages(fake.predictions[0]["result"]) == {"aftermath": (15, 24)}

    def test_the_confidence_becomes_the_score(self) -> None:
        fake = FakeServer()
        labelstudio.add_drafts(fake, "divyansh", DRAFTS, model_version="v1")
        assert {p["task"]: p["score"] for p in fake.predictions} == {10: 0.7, 11: 0.3}

    def test_only_this_annotators_projects_are_used_and_set_to_pre_fill(self) -> None:
        fake = FakeServer()
        report = labelstudio.add_drafts(fake, "divyansh", DRAFTS, model_version="v1")
        assert report["projects"] == [1, 2]
        assert sorted(fake.patched) == [(1, {"model_version": "v1"}), (2, {"model_version": "v1"})]
        assert 12 not in {p["task"] for p in fake.predictions}  # someone else's clip

    def test_running_twice_adds_nothing_the_second_time(self) -> None:
        fake = FakeServer()
        labelstudio.add_drafts(fake, "divyansh", DRAFTS, model_version="v1")
        again = labelstudio.add_drafts(fake, "divyansh", DRAFTS, model_version="v1")
        assert (again["added"], again["already_there"]) == (0, 2) and len(fake.predictions) == 2

    def test_a_new_version_is_added_beside_the_old(self) -> None:
        fake = FakeServer()
        labelstudio.add_drafts(fake, "divyansh", DRAFTS, model_version="v1")
        labelstudio.add_drafts(fake, "divyansh", DRAFTS, model_version="v2")
        assert sorted(p["model_version"] for p in fake.predictions) == ["v1", "v1", "v2", "v2"]

    def test_a_draft_for_a_clip_that_is_not_a_task_is_reported_not_dropped_silently(self) -> None:
        fake = FakeServer()
        report = labelstudio.add_drafts(
            fake,
            "divyansh",
            [*DRAFTS, {"candidate_id": "ucf_crime:Nope", "stages": STAGES}],
            model_version="v1",
        )
        assert report["no_task"] == ["ucf_crime:Nope"] and report["added"] == 2

    def test_a_project_is_only_pointed_at_a_version_it_has_predictions_for(self) -> None:
        fake = FakeServer()
        labelstudio.add_drafts(fake, "divyansh", DRAFTS[:1], model_version="v1")
        assert [p for p, _ in fake.patched] == [
            1
        ]  # project 2 has none, and Label Studio refuses it

    def test_a_bad_draft_stops_the_run_with_a_message(self) -> None:
        fake = FakeServer()
        bad = [{"candidate_id": "ucf_crime:A", "stages": [["action", 30, 40]]}]
        with pytest.raises(labelstudio.LabelStudioError, match="does not fit"):
            labelstudio.add_drafts(fake, "divyansh", bad, model_version="v1")


class TestCommand:
    def file(self, tmp_path: Path) -> Path:
        path = tmp_path / "drafts.json"
        path.write_text(json.dumps({"model_version": "v1", "clips": DRAFTS}))
        return path

    def test_loads_the_file_and_says_what_it_did(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake = FakeServer()
        monkeypatch.setattr(cli.labelstudio, "http_transport", lambda url, token: fake)
        monkeypatch.setenv("LABEL_STUDIO_TOKEN", "t")
        assert main(["ls-drafts", str(self.file(tmp_path)), "--annotator", "divyansh"]) == 0
        assert (
            "2 drafts added, 0 already there, projects [1, 2] now pre-fill from v1"
            in capsys.readouterr().out
        )

    def test_a_missing_task_makes_the_exit_code_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(cli.labelstudio, "http_transport", lambda url, token: FakeServer())
        monkeypatch.setenv("LABEL_STUDIO_TOKEN", "t")
        path = tmp_path / "d.json"
        path.write_text(
            json.dumps(
                {"model_version": "v1", "clips": [{"candidate_id": "x:none", "stages": STAGES}]}
            )
        )
        assert main(["ls-drafts", str(path), "--annotator", "divyansh"]) == 1
        assert "no task for: x:none" in capsys.readouterr().err

    def test_without_a_token_it_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("LABEL_STUDIO_TOKEN", raising=False)
        assert main(["ls-drafts", str(self.file(tmp_path)), "--annotator", "divyansh"]) == 2
        assert "LABEL_STUDIO_TOKEN" in capsys.readouterr().err


@pytest.fixture(scope="module")
def committed() -> dict:
    root = Path(__file__).resolve().parents[4]
    return json.loads((root / "ml/annotation/drafts/claude-draft-1.json").read_text())


class TestTheCommittedDrafts:
    """claude-draft-1.json is data a person will rely on, so it must be well formed."""

    def test_it_says_who_made_it_and_how_to_read_it(self, committed: dict) -> None:
        assert (
            committed["model_version"] == "claude-draft-1" and "Claude" in committed["drafted_by"]
        )
        assert "drafts for a person to correct" in committed["how_to_read"]

    def test_every_clip_has_valid_ordered_stages_and_a_known_confidence(
        self, committed: dict
    ) -> None:
        clips = committed["clips"]
        assert len(clips) == len({c["candidate_id"] for c in clips}) == 103
        for clip in clips:
            assert clip["confidence"] in labelstudio.CONFIDENCE_SCORE
            labelstudio.draft_result(
                clip["stages"], frames=10_000, fps=1, primary_view="x", event_type="y"
            )

    def test_a_draft_that_was_not_looked_at_says_so_and_is_never_more_than_a_prior(
        self, committed: dict
    ) -> None:
        for clip in committed["clips"]:
            assert clip["how"] in {"frames", "padding rule"}
            if clip["how"] == "padding rule":
                assert clip["confidence"] == "prior" and "not looked at" in clip["note"]
                assert clip["candidate_id"].startswith("meva:")

    def test_the_padding_rule_drafts_follow_the_rule(self, committed: dict) -> None:
        rule = [c for c in committed["clips"] if c["how"] == "padding rule"]
        assert len(rule) == 45
        for clip in rule:
            names = [stage[0] for stage in clip["stages"]]
            assert names[:2] == ["baseline", "action"] and clip["stages"][0][1:] == [0, 10]
            assert clip["stages"][1][1] == 10 and set(names) <= {"baseline", "action", "aftermath"}
