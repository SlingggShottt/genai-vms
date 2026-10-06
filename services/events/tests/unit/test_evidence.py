"""The evidence a candidate carries for the VLM gate (P3-D4) — pure."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from events.domain.evidence import (
    MAX_BOXES,
    MAX_KEPT,
    EvidenceFrame,
    add_evidence,
    evidence_of,
    frame_evidence,
    spread,
)
from events.domain.state import Episode
from vms_common.contracts.twin import Frame

T0 = datetime(2026, 10, 1, 7, 0, 0, tzinfo=UTC)


def evidence(n: int) -> EvidenceFrame:
    return EvidenceFrame(
        ts=T0 + timedelta(seconds=n),
        segment_id="cam01_seg",
        keyframe_uri=f"s3://vms-keyframes/cam01/{n:04d}.jpg",
    )


class TestTheLimitsAsWritten:
    """What is stored per candidate (and checkpointed to Redis every segment) is bounded by these;
    pinned as numbers, not just as the constants the other tests import."""

    def test_the_numbers(self) -> None:
        assert (MAX_KEPT, MAX_BOXES) == (16, 8)


class TestSpread:
    def test_the_picks_are_rounded_not_floored(self) -> None:
        assert spread(list(range(12)), 4) == [0, 4, 7, 11]  # 11/3 = 3.67 -> 4, 7.33 -> 7
        assert spread(list(range(10)), 4) == [0, 3, 6, 9]
        assert spread(list(range(13)), 5) == [0, 3, 6, 9, 12]

    def test_all_of_them_when_there_are_no_more_than_asked_for(self) -> None:
        assert spread([1, 2, 3], 3) == [1, 2, 3]
        assert spread([1, 2, 3], 9) == [1, 2, 3]

    def test_evenly_spaced_and_including_both_ends(self) -> None:
        assert spread(list(range(11)), 3) == [0, 5, 10]
        assert spread(list(range(11)), 2) == [0, 10]

    def test_one_is_the_latest(self) -> None:
        assert spread(list(range(11)), 1) == [10]

    def test_none_asked_for_none_returned(self) -> None:
        assert spread([1, 2, 3], 0) == []
        assert spread([1, 2, 3], -1) == []

    @pytest.mark.parametrize("n", range(5, 40))
    def test_four_of_any_length_are_distinct_in_order_with_both_ends(self, n: int) -> None:
        picked = spread(list(range(n)), 4)
        assert picked[0] == 0 and picked[-1] == n - 1
        assert picked == sorted(set(picked)) and len(picked) == 4

    def test_the_input_is_not_modified(self) -> None:
        items = list(range(10))
        spread(items, 3)
        assert items == list(range(10))


class TestAddEvidence:
    def test_grows_until_the_limit(self) -> None:
        kept: list[EvidenceFrame] = []
        for n in range(MAX_KEPT):
            kept = add_evidence(kept, evidence(n))
        assert [f.ts for f in kept] == [evidence(n).ts for n in range(MAX_KEPT)]

    def test_one_more_than_the_limit_thins_to_half_keeping_first_and_latest(self) -> None:
        kept: list[EvidenceFrame] = []
        for n in range(MAX_KEPT + 1):
            kept = add_evidence(kept, evidence(n))
        assert len(kept) == MAX_KEPT // 2
        assert kept[0] == evidence(0) and kept[-1] == evidence(MAX_KEPT)
        assert kept == sorted(kept, key=lambda f: f.ts)

    def test_a_long_episode_stays_bounded_and_still_spans_it(self) -> None:
        kept: list[EvidenceFrame] = []
        for n in range(500):
            kept = add_evidence(kept, evidence(n))
            assert len(kept) <= MAX_KEPT
        assert kept[0] == evidence(0) and kept[-1] == evidence(499)
        assert len(kept) > 1

    def test_a_frame_already_kept_is_not_added_twice(self) -> None:
        kept = add_evidence([evidence(0)], evidence(0))
        assert kept == [evidence(0)]

    def test_the_input_list_is_not_modified(self) -> None:
        kept = [evidence(0)]
        add_evidence(kept, evidence(1))
        assert kept == [evidence(0)]

    def test_a_smaller_limit_thins_sooner(self) -> None:
        kept: list[EvidenceFrame] = []
        for n in range(5):
            kept = add_evidence(kept, evidence(n), limit=4)
        assert kept == [evidence(0), evidence(4)]  # thinned to limit // 2


class TestFrameEvidence:
    def frame(self, make: SimpleNamespace, objects: list) -> Frame:
        return Frame(
            ts=T0, idx=0, keyframe_uri="s3://vms-keyframes/cam01/0000.jpg", objects=objects
        )

    def test_only_the_flagged_tracks_are_boxed(self, make: SimpleNamespace) -> None:
        frame = self.frame(make, [make.obj("t1"), make.obj("t2", center=(0.7, 0.7))])
        result = frame_evidence(frame, "seg-1", ["t2"])
        assert [b.track_id for b in result.boxes] == ["t2"]
        assert result.boxes[0].category == "person"
        assert result.boxes[0].bbox == pytest.approx((0.65, 0.65, 0.75, 0.75))
        assert (result.segment_id, result.keyframe_uri, result.ts) == (
            "seg-1",
            "s3://vms-keyframes/cam01/0000.jpg",
            T0,
        )

    def test_a_track_that_is_not_in_the_frame_adds_no_box(self, make: SimpleNamespace) -> None:
        result = frame_evidence(self.frame(make, [make.obj("t1")]), "seg-1", ["t9"])
        assert result.boxes == []

    def test_a_crowd_is_drawn_by_its_most_confident_members(self, make: SimpleNamespace) -> None:
        people = [make.obj(f"t{n}", conf=0.5 + n / 100) for n in range(MAX_BOXES + 4)]
        result = frame_evidence(self.frame(make, people), "seg-1", [p.track_id for p in people])
        assert len(result.boxes) == MAX_BOXES
        assert result.boxes[0].track_id == f"t{MAX_BOXES + 3}"
        assert {b.track_id for b in result.boxes} == {f"t{n}" for n in range(4, MAX_BOXES + 4)}


class TestReadingEvidenceBack:
    def test_comes_back_oldest_first_whatever_order_it_was_stored_in(self) -> None:
        stored = [evidence(n).model_dump(mode="json") for n in (3, 1, 2, 0)]
        assert [f.ts for f in evidence_of({"evidence": stored})] == [
            evidence(n).ts for n in range(4)
        ]

    @pytest.mark.parametrize("details", [{}, {"evidence": None}, {"evidence": []}, {"frames": 7}])
    def test_a_candidate_with_none_has_none(self, details: dict) -> None:
        assert evidence_of(details) == []

    def test_an_entry_that_does_not_parse_is_left_out_and_the_rest_are_kept(self) -> None:
        stored = [{"nonsense": True}, evidence(1).model_dump(mode="json"), "not even a dict", None]
        assert evidence_of({"evidence": stored}) == [evidence(1)]


class TestThroughTheEngine:
    """A candidate's `details["evidence"]`, as the database will hold it."""

    def sequence(self, make: SimpleNamespace) -> tuple[list, list]:
        people = [make.obj("cam01-t1"), make.obj("cam01-t2", center=(0.7, 0.7))]
        zones = [make.zone("yard", "generic")]
        return make.twins(make.frames(95, people), total_s=120), zones

    def test_each_candidate_carries_boxes_for_its_own_track_only(
        self, make: SimpleNamespace
    ) -> None:
        twins, zones = self.sequence(make)
        latest = make.run(twins, zones).latest()
        assert len(latest) == 2
        for update in latest.values():
            kept = update.details["evidence"]
            assert kept, "a closed candidate has evidence"
            for frame in kept:
                assert {b["track_id"] for b in frame["boxes"]} == set(update.track_ids)

    def test_it_is_bounded_in_time_order_and_spans_the_episode(self, make: SimpleNamespace) -> None:
        twins, zones = self.sequence(make)
        for update in make.run(twins, zones).latest().values():
            kept = update.details["evidence"]
            stamps = [datetime.fromisoformat(f["ts"]) for f in kept]
            assert 1 < len(kept) <= MAX_KEPT
            assert stamps == sorted(stamps)
            assert stamps[0] == make.T0  # the first hit frame
            assert stamps[-1] == update.end_ts  # the latest one
            assert all(update.start_ts <= s <= update.end_ts for s in stamps)
            assert {f["segment_id"] for f in kept} <= set(update.segment_ids)

    def test_the_details_are_plain_json(self, make: SimpleNamespace) -> None:
        twins, zones = self.sequence(make)
        update = next(iter(make.run(twins, zones).latest().values()))
        assert json.loads(json.dumps(update.details)) == update.details

    def test_state_saved_before_evidence_existed_still_loads(self, make: SimpleNamespace) -> None:
        twins, zones = self.sequence(make)
        state = make.run(twins[:8], zones).state
        episode = next(iter(state.episodes.values()))
        old = episode.model_dump(mode="json")
        del old["evidence"]
        assert Episode.model_validate(old).evidence == []
