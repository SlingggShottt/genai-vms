from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from annotation_kit import combine
from annotation_kit.candidates import PhaseCandidate, ViewSpec, write_candidates
from annotation_kit.cli import main
from annotation_kit.schema import ClipView, PhaseLabelClip, PhaseSpan
from annotation_kit.tasks import read_phase_labels


def cand(
    name: str, *, dataset: str = "ucf_crime", seconds: float = 20.0, views: int = 1
) -> PhaseCandidate:
    cams = [f"cam0{i + 1}" for i in range(views)]
    return PhaseCandidate(
        candidate_id=f"{dataset}:{name}",
        dataset=dataset,  # type: ignore[arg-type]
        source_video=f"{dataset}:{name}",
        event_type="robbery",
        primary_view=cams[0],
        views=[
            ViewSpec(camera=c, source_uri=f"x://{name}.mp4", start_s=0, end_s=seconds) for c in cams
        ],
    )


def mark(phase: str, a: int, b: int) -> dict[str, Any]:
    return {"from_name": "phase", "to_name": "video", "type": "timelinelabels",
            "value": {"ranges": [{"start": a, "end": b}], "timelinelabels": [phase]}}  # fmt: skip


def choice(name: str, value: str) -> dict[str, Any]:
    return {"from_name": name, "to_name": "video", "type": "choices", "value": {"choices": [value]}}


def person(
    c: PhaseCandidate, marks: list, *, draft: list | None = None, version: str = "v1"
) -> dict:
    answers = [
        choice("usable", "Yes"),
        choice("primary_view", c.primary_view),
        choice("event_type", "robbery"),
    ]
    annotation: dict[str, Any] = {
        "id": 1,
        "was_cancelled": False,
        "result": [*marks, *answers],
        "updated_at": "2026-10-24T10:00:00Z",
    }
    if draft is not None:
        annotation["prediction"] = {"result": [*draft, *answers], "model_version": version}
    clips = [
        {"camera": v.camera, "video_uri": f"local://clips/{c.candidate_id}/{v.camera}.mp4"}
        for v in c.views
    ]
    data = {
        "candidate_id": c.candidate_id,
        "dataset": c.dataset,
        "source_video": c.source_video,
        "event_type": c.event_type,
        "primary_view": c.primary_view,
        "clips": clips,
        "duration_s": c.duration_s,
        "timeline_fps": 1,
    }
    return {"data": data, "annotations": [annotation]}


def doc(version: str, **clips: tuple[str, list]) -> dict:
    items = [
        {"candidate_id": cid, "how": how, "confidence": "seen", "stages": stages}
        for cid, (how, stages) in clips.items()
    ]
    return {"model_version": version, "clips": items}


A, B, C, D = cand("A"), cand("B"), cand("C"), cand("D")
STAGES = [["baseline", 0, 5], ["action", 5, 12], ["aftermath", 12, 20]]
MARKS = [
    mark("baseline", 1, 5),
    mark("action", 6, 12),
    mark("aftermath", 13, 20),
]  # the same stages, as frames


def names(result: combine.Combined) -> dict[str, str]:
    return {c.clip_id.split(":")[1]: c.annotator for c in result.clips}


class TestWhichSourceWins:
    def test_a_persons_marks_beat_a_draft_and_a_draft_beats_a_dataset_span(self) -> None:
        span = PhaseLabelClip(
            clip_id=C.candidate_id,
            source_video=C.source_video,
            event_type="robbery",
            primary_view="cam01",
            views=[ClipView(camera="cam01", video_uri="local://x")],
            phases=[PhaseSpan(phase="action", start_s=2, end_s=9)],
        )
        result = combine.combine(
            [A, B, C, D],
            hand_export=[person(A, MARKS)],
            drafts=[
                doc(
                    "v1", **{A.candidate_id: ("frames", STAGES), B.candidate_id: ("frames", STAGES)}
                )
            ],
            span_labels=[span],
        )
        assert names(result) == {
            "A": "human:from-scratch",
            "B": "draft:v1:frames",
            "C": combine.SPAN,
        }
        assert result.missing == [D.candidate_id]

    def test_a_later_drafts_file_replaces_an_earlier_one_for_the_same_clip(self) -> None:
        first = doc("v1", **{A.candidate_id: ("padding rule", STAGES)})
        second = doc("v2", **{A.candidate_id: ("zoomed frames", [["action", 3, 9]])})
        (clip,) = combine.combine([A], drafts=[first, second]).clips
        assert clip.annotator == "draft:v2:zoomed-frames" and [p.phase for p in clip.phases] == [
            "action"
        ]

    def test_the_order_of_the_candidates_is_kept(self) -> None:
        result = combine.combine(
            [C, A, B], drafts=[doc("v1", **{x.candidate_id: ("frames", STAGES) for x in (A, B, C)})]
        )
        assert [c.clip_id for c in result.clips] == [C.candidate_id, A.candidate_id, B.candidate_id]


class TestThePersonsLabelsSaySWhatTheyAre:
    def test_marked_with_no_draft_behind_it_is_from_scratch(self) -> None:
        assert names(combine.combine([A], hand_export=[person(A, MARKS)])) == {
            "A": "human:from-scratch"
        }

    def test_a_draft_submitted_as_it_was_is_accepted_not_from_scratch(self) -> None:
        item = person(A, MARKS, draft=MARKS, version="v1")
        assert names(combine.combine([A], hand_export=[item])) == {"A": "human:accepted-draft:v1"}

    def test_a_draft_that_was_changed_is_corrected(self) -> None:
        changed = [mark("baseline", 1, 5), mark("action", 6, 14), mark("aftermath", 15, 20)]
        item = person(A, changed, draft=MARKS, version="v2")
        assert names(combine.combine([A], hand_export=[item])) == {"A": "human:corrected-draft:v2"}

    def test_the_persons_marks_not_the_drafts_are_what_is_kept(self) -> None:
        changed = [mark("baseline", 1, 5), mark("action", 6, 14), mark("aftermath", 15, 20)]
        (clip,) = combine.combine(
            [A],
            hand_export=[person(A, changed, draft=MARKS)],
            drafts=[doc("v1", **{A.candidate_id: ("frames", STAGES)})],
        ).clips
        assert [(p.phase, p.start_s, p.end_s) for p in clip.phases] == [
            ("baseline", 0, 5),
            ("action", 5, 14),
            ("aftermath", 14, 20),
        ]

    def test_marks_the_converter_rejects_fall_back_to_the_draft_and_say_so(self) -> None:
        overlapping = [mark("baseline", 1, 12), mark("action", 5, 12)]
        result = combine.combine(
            [A],
            hand_export=[person(A, overlapping)],
            drafts=[doc("v1", **{A.candidate_id: ("frames", STAGES)})],
        )
        assert (
            names(result) == {"A": "draft:v1:frames"}
            and "rejected by the converter" in result.notes[0]
        )

    def test_a_skipped_clip_is_not_a_human_label(self) -> None:
        skipped = {
            "data": person(A, [])["data"],
            "annotations": [{"id": 1, "was_cancelled": True, "result": []}],
        }
        result = combine.combine(
            [A], hand_export=[skipped], drafts=[doc("v1", **{A.candidate_id: ("frames", STAGES)})]
        )
        assert names(result) == {"A": "draft:v1:frames"} and result.notes == []


class TestTurningADraftIntoALabel:
    def test_stages_are_seconds_cut_to_the_clip_and_the_views_are_the_clips(self) -> None:
        c = cand("M", dataset="meva", seconds=20.0, views=2)
        item = {"how": "zoomed frames", "stages": [["baseline", 0, 10], ["action", 10, 26]]}
        label = combine.draft_clip(c, item, version="v2", clip_prefix="local://clips")
        assert label is not None
        assert [(p.phase, p.start_s, p.end_s) for p in label.phases] == [
            ("baseline", 0, 10),
            ("action", 10, 20),
        ]
        assert [v.camera for v in label.views] == ["cam01", "cam02"] and label.views[
            0
        ].video_uri == "local://clips/meva_M/cam01.mp4"
        assert label.annotator == "draft:v2:zoomed-frames" and label.primary_view == "cam01"

    def test_a_stage_past_the_end_or_shorter_than_a_tenth_of_a_second_is_dropped(self) -> None:
        item = {"stages": [["baseline", 0, 10], ["action", 10, 10.05], ["aftermath", 25, 30]]}
        label = combine.draft_clip(A, item, version="v1", clip_prefix="p")
        assert label is not None and [p.phase for p in label.phases] == ["baseline"]

    def test_a_draft_with_nothing_left_is_none_and_the_next_source_is_tried(self) -> None:
        assert (
            combine.draft_clip(A, {"stages": [["action", 30, 40]]}, version="v1", clip_prefix="p")
            is None
        )
        result = combine.combine(
            [A], drafts=[doc("v1", **{A.candidate_id: ("frames", [["action", 30, 40]])})]
        )
        assert (
            result.clips == []
            and result.missing == [A.candidate_id]
            and "no usable stage" in result.notes[0]
        )

    def test_a_draft_without_a_how_is_called_frames(self) -> None:
        label = combine.draft_clip(A, {"stages": STAGES}, version="v1", clip_prefix="p")
        assert label is not None and label.annotator == "draft:v1:frames"


class TestGroups:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("human:from-scratch", "human"),
            ("human:accepted-draft:v1", "human"),
            ("human:corrected-draft:v2", "human"),
            ("draft:v1:frames", "model draft (looked at the clip)"),
            ("draft:v2:zoomed-frames", "model draft (looked at the clip)"),
            ("draft:v2:padding-rule", "model draft (rule only)"),
            ("dataset-span:ucf-crime", "dataset span"),
            ("someone", "unknown"),
            ("humanoid", "unknown"),
            ("hand", "unknown"),
            (None, "unknown"),
        ],
    )
    def test_each_source_has_one_group(self, source: str | None, expected: str) -> None:
        assert combine.group(source) == expected

    def test_the_counts_and_the_table(self) -> None:
        drafts = doc(
            "v1", **{B.candidate_id: ("frames", STAGES), C.candidate_id: ("padding rule", STAGES)}
        )
        result = combine.combine([A, B, C], hand_export=[person(A, MARKS)], drafts=[drafts])
        assert result.counts() == {
            "human": 1,
            "model draft (looked at the clip)": 1,
            "model draft (rule only)": 1,
        }
        table = combine.summary_table(result)
        assert "| human | 1 |" in table and "| draft:v1:padding-rule | 1 |" in table


class TestCommand:
    @pytest.fixture
    def files(self, tmp_path: Path) -> dict[str, Path]:
        candidates = tmp_path / "candidates.json"
        write_candidates([A, B, C], candidates)
        export = tmp_path / "export.json"
        export.write_text(json.dumps([person(A, MARKS, draft=MARKS, version="v1")]))
        drafts = tmp_path / "drafts.json"
        drafts.write_text(json.dumps(doc("v1", **{B.candidate_id: ("frames", STAGES)})))
        return {
            "candidates": candidates,
            "export": export,
            "drafts": drafts,
            "out": tmp_path / "all.jsonl",
        }

    def run(self, files: dict[str, Path], *extra: str) -> int:
        args = ["combine-labels", str(files["candidates"])]
        args += ["--hand-export", str(files["export"]), "--drafts", str(files["drafts"])]
        return main([*args, "--out", str(files["out"]), *extra])

    def test_writes_labels_that_say_where_each_came_from_and_reports_the_ones_left(
        self, files, capsys
    ) -> None:
        assert self.run(files) == 1  # C has no label from any source
        out, err = capsys.readouterr()
        assert {c.clip_id.split(":")[1]: c.annotator for c in read_phase_labels(files["out"])} == {
            "A": "human:accepted-draft:v1", "B": "draft:v1:frames"}  # fmt: skip
        assert (
            "2 of 3 clips labelled" in out and f"no label from any source: {C.candidate_id}" in err
        )

    def test_drafts_files_given_later_on_the_command_line_win(self, files, tmp_path: Path) -> None:
        second = tmp_path / "drafts2.json"
        second.write_text(
            json.dumps(doc("v2", **{B.candidate_id: ("zoomed frames", [["action", 1, 5]])}))
        )
        self.run(files, "--drafts", str(second))
        labels = {c.clip_id.split(":")[1]: c for c in read_phase_labels(files["out"])}
        assert labels["B"].annotator == "draft:v2:zoomed-frames"
        assert [p.phase for p in labels["B"].phases] == ["action"]

    def test_with_everything_labelled_the_exit_code_is_zero(self, files) -> None:
        files["drafts"].write_text(
            json.dumps(
                doc(
                    "v1", **{B.candidate_id: ("frames", STAGES), C.candidate_id: ("frames", STAGES)}
                )
            )
        )
        assert self.run(files) == 0
