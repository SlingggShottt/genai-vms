from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from annotation_kit import draftedits
from annotation_kit.cli import main


def mark(phase: str, start: int, end: int) -> dict[str, Any]:
    return {
        "from_name": "phase",
        "to_name": "video",
        "type": "timelinelabels",
        "value": {"ranges": [{"start": start, "end": end}], "timelinelabels": [phase]},
    }


def choice(name: str, value: str) -> dict[str, Any]:
    return {"from_name": name, "to_name": "video", "type": "choices", "value": {"choices": [value]}}


DRAFT = [
    mark("baseline", 1, 10),
    mark("action", 11, 20),
    mark("aftermath", 21, 30),
    choice("event_type", "robbery"),
    choice("usable", "Yes"),
]


def task(cid: str, final: list, *, draft: list | None = DRAFT, version: str = "v1", **ann) -> dict:
    annotation: dict[str, Any] = {
        "id": 1,
        "was_cancelled": False,
        "result": final,
        "updated_at": "2026-10-17T10:00:00Z",
    }
    if draft is not None:
        annotation["prediction"] = {"result": draft, "model_version": version, "score": 0.7}
    annotation.update(ann)
    return {"data": {"candidate_id": cid, "timeline_fps": 1}, "annotations": [annotation]}


class TestComparing:
    def test_a_draft_submitted_untouched_is_identical(self) -> None:
        got = draftedits.compare(DRAFT, list(DRAFT), fps=1)
        assert (
            got["identical"]
            and got["iou"] == 1.0
            and got["moved"] == []
            and got["mean_shift_s"] is None
        )

    def test_a_moved_boundary_is_named_and_measured_in_seconds(self) -> None:
        final = [mark("baseline", 1, 10), mark("action", 11, 24), mark("aftermath", 21, 30)]
        got = draftedits.compare(DRAFT, final + DRAFT[3:], fps=1)
        assert not got["identical"] and got["moved"] == ["action"]
        assert got["mean_shift_s"] == 2.0  # one end moved 4 s, the other 0
        assert 0.6 < got["iou"] < 1.0

    def test_the_shift_is_in_seconds_at_the_rate_the_clip_was_marked_at(self) -> None:
        final = [mark("action", 11, 24)]
        got = draftedits.compare([mark("action", 11, 20)], final, fps=2)
        assert (
            got["mean_shift_s"] == 1.0
        )  # 4 frames on one end, over two ends, at 2 frames a second

    def test_a_stage_added_or_removed_counts_as_no_overlap_for_it(self) -> None:
        final = [mark("baseline", 1, 10), mark("precursor", 11, 14), mark("action", 15, 20)]
        got = draftedits.compare(DRAFT, final, fps=1)
        assert got["added"] == ["precursor"] and got["removed"] == ["aftermath"]
        assert got["iou"] < 0.5

    def test_a_changed_answer_is_not_identical_even_if_the_stages_are(self) -> None:
        final = DRAFT[:3] + [choice("event_type", "burglary"), choice("usable", "Yes")]
        got = draftedits.compare(DRAFT, final, fps=1)
        assert (
            not got["identical"] and got["answers_changed"] == ["event_type"] and got["moved"] == []
        )

    def test_overlap_of_one_frame_stages_is_counted_by_frames_not_by_stage(self) -> None:
        assert draftedits._iou((1, 1), (1, 1)) == 1.0
        assert draftedits._iou((1, 2), (2, 3)) == pytest.approx(1 / 3)
        assert draftedits._iou((1, 2), (5, 6)) == 0.0


class TestWhichClipsWereDrafted:
    def test_a_clip_with_a_prediction_behind_it_is_a_draft_and_one_without_is_from_scratch(
        self,
    ) -> None:
        edits = draftedits.clip_edits([task("a", list(DRAFT)), task("b", list(DRAFT), draft=None)])
        assert [(e.clip_id, e.origin) for e in edits] == [("a", "v1"), ("b", "scratch")]
        assert edits[0].identical and edits[0].score == 0.7 and edits[1].iou is None

    def test_a_draft_from_another_model_counts_as_from_scratch_when_one_is_asked_for(self) -> None:
        export = [task("a", list(DRAFT), version="v1"), task("b", list(DRAFT), version="v2")]
        edits = draftedits.clip_edits(export, model_version="v1")
        assert [(e.clip_id, e.origin) for e in edits] == [("a", "v1"), ("b", "scratch")]

    def test_skipped_or_empty_annotations_are_left_out(self) -> None:
        export = [task("a", [], draft=None), task("b", list(DRAFT), was_cancelled=True)]
        assert draftedits.clip_edits(export) == []

    def test_the_latest_finished_annotation_is_the_one_compared(self) -> None:
        old = {"id": 1, "result": [mark("action", 1, 5)], "updated_at": "2026-10-17T09:00:00Z"}
        new = {
            "id": 2,
            "result": list(DRAFT),
            "updated_at": "2026-10-17T11:00:00Z",
            "prediction": {"result": DRAFT, "model_version": "v1"},
        }
        for order in ([new, old], [old, new]):  # whichever way round Label Studio lists them
            (edit,) = draftedits.clip_edits([{"data": {"candidate_id": "a"}, "annotations": order}])
            assert edit.identical


class TestSummary:
    def edits(self, n_same: int, n_changed: int, n_scratch: int = 0) -> list:
        changed = [
            mark("baseline", 1, 10),
            mark("action", 11, 24),
            mark("aftermath", 21, 30),
        ] + DRAFT[3:]
        export = [task(f"s{i}", list(DRAFT)) for i in range(n_same)]
        export += [task(f"c{i}", changed) for i in range(n_changed)]
        export += [task(f"h{i}", list(DRAFT), draft=None) for i in range(n_scratch)]
        return draftedits.clip_edits(export)

    def test_the_counts_and_the_share_accepted_unchanged(self) -> None:
        s = draftedits.summarise(self.edits(3, 1, 2))
        assert (s["clips"], s["from_scratch"], s["from_a_draft"]) == (6, 2, 4)
        assert s["submitted_exactly_as_drafted"] == 3 and s["share_unchanged"] == 0.75
        assert s["stage_changes"] == {"moved": 1, "added": 0, "removed": 0}
        assert s["drafted_clips"] == ["c0", "s0", "s1", "s2"] and s["scratch_clips"] == ["h0", "h1"]

    def test_the_two_kinds_of_clip_are_listed_apart_for_scoring(self) -> None:
        s = draftedits.summarise(self.edits(1, 1, 1))
        assert not set(s["drafted_clips"]) & set(s["scratch_clips"])

    def test_nothing_drafted_gives_no_shares_not_a_division_by_zero(self) -> None:
        s = draftedits.summarise(self.edits(0, 0, 2))
        assert (
            s["from_a_draft"] == 0
            and s["share_unchanged"] is None
            and s["mean_iou_with_the_draft"] is None
        )

    def test_accepting_nearly_everything_is_flagged_once_there_are_enough_clips(self) -> None:
        edits = self.edits(10, 0)
        assert "Nearly everything was accepted unchanged" in draftedits.markdown(
            edits, draftedits.summarise(edits)
        )
        few = self.edits(3, 0)
        assert "Nearly everything" not in draftedits.markdown(few, draftedits.summarise(few))

    def test_changing_everything_is_flagged_too(self) -> None:
        edits = self.edits(0, 6)
        assert "Nothing was accepted as drafted" in draftedits.markdown(
            edits, draftedits.summarise(edits)
        )

    def test_most_but_not_nearly_all_accepted_is_not_flagged(self) -> None:
        edits = self.edits(7, 3)  # 70 %: a lot, but 90 % is where it starts to look unchecked
        assert "Nearly everything" not in draftedits.markdown(edits, draftedits.summarise(edits))

    def test_a_healthy_mix_is_not_flagged(self) -> None:
        edits = self.edits(4, 6)
        text = draftedits.markdown(edits, draftedits.summarise(edits))
        assert "Nearly everything" not in text and "Nothing was accepted" not in text
        assert "4 were submitted exactly as drafted (40%)" in text


class TestCommand:
    def test_prints_the_table_and_writes_the_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        export = tmp_path / "export.json"
        export.write_text(
            json.dumps([task("clip-1", list(DRAFT)), task("clip-2", list(DRAFT), draft=None)])
        )
        out = tmp_path / "summary.json"
        assert main(["draft-edits", str(export), "--json", str(out)]) == 0
        text = capsys.readouterr().out
        assert "| clip-1 | draft | yes |" in text and "| clip-2 | from scratch |" in text
        assert json.loads(out.read_text())["scratch_clips"] == ["clip-2"]

    def test_the_model_version_filter_reaches_the_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        export = tmp_path / "export.json"
        export.write_text(json.dumps([task("a", list(DRAFT), version="old")]))
        main(["draft-edits", str(export), "--model-version", "new"])
        assert "| a | from scratch |" in capsys.readouterr().out
