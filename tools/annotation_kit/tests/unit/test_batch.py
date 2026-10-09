from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from annotation_kit import batch
from annotation_kit.candidates import PhaseCandidate, ViewSpec, read_candidates, write_candidates
from annotation_kit.cli import main


def cand(n: int, activity: str, *, slot: int | None = None, views: int = 2) -> PhaseCandidate:
    cams = [f"G{400 + i}" for i in range(views)]
    return PhaseCandidate(
        candidate_id=f"{activity}-{n:03d}",
        dataset="meva",
        source_video=f"slot-{n if slot is None else slot}",
        event_type="activity",
        activity=activity,
        primary_view=cams[0],
        views=[
            ViewSpec(camera=c, source_uri=f"s3://b/{c}.avi", start_s=10, end_s=40) for c in cams
        ],
    )


def pool() -> list[PhaseCandidate]:
    return (
        [cand(i, "vehicle_drops_off_person") for i in range(30)]
        + [cand(100 + i, "person_embraces_person") for i in range(30)]
        + [cand(200 + i, "person_transfers_object") for i in range(30)]
        + [cand(300 + i, "person_steals_object") for i in range(3)]
    )


def kinds(items) -> Counter:
    return Counter(c.activity for c in items)


class TestPickBatch:
    def test_the_size_asked_for(self) -> None:
        assert len(batch.pick_batch(pool(), 24)) == 24

    def test_every_rare_activity_is_in_whatever_the_size(self) -> None:
        assert kinds(batch.pick_batch(pool(), 12))["person_steals_object"] == 3

    def test_an_activity_with_exactly_the_rare_limit_counts_as_rare_and_one_more_does_not(
        self,
    ) -> None:
        many = [cand(i, "vehicle_drops_off_person") for i in range(40)]
        at_limit = [cand(100 + i, "person_steals_object") for i in range(batch.RARE_AT_MOST)]
        over_limit = [
            cand(200 + i, "person_embraces_person") for i in range(batch.RARE_AT_MOST + 1)
        ]
        counts = kinds(batch.pick_batch(many + at_limit + over_limit, batch.RARE_AT_MOST + 1))
        assert (
            counts["person_steals_object"] == batch.RARE_AT_MOST
        )  # all of them, ahead of the rest
        assert counts["person_embraces_person"] <= 1  # not rare: it only gets its turn

    def test_a_batch_smaller_than_the_rare_ones_still_has_the_size_asked_for(self) -> None:
        assert len(batch.pick_batch(pool(), 2)) == 2

    def test_the_common_activities_share_what_is_left_evenly(self) -> None:
        counts = kinds(batch.pick_batch(pool(), 30))
        common = [
            counts[a]
            for a in (
                "vehicle_drops_off_person",
                "person_embraces_person",
                "person_transfers_object",
            )
        ]
        assert sum(common) == 27 and max(common) - min(common) <= 1

    def test_one_clip_per_source_video_while_others_remain(self) -> None:
        # 30 clips of one activity share 3 slots; 30 more are all in different slots
        crowded = [cand(i, "vehicle_drops_off_person", slot=i % 3) for i in range(30)]
        spread = [cand(100 + i, "person_embraces_person") for i in range(30)]
        chosen = batch.pick_batch(crowded + spread, 20)
        sources = [c.source_video for c in chosen]
        assert len(set(sources)) == len(sources)

    def test_repeats_a_source_only_when_nothing_else_is_left(self) -> None:
        crowded = [cand(i, "vehicle_drops_off_person", slot=i % 2) for i in range(10)]
        chosen = batch.pick_batch(crowded, 6)
        assert len(chosen) == 6 and len({c.source_video for c in chosen}) == 2

    def test_a_pool_smaller_than_the_size_gives_all_of_it_once(self) -> None:
        chosen = batch.pick_batch(pool()[:5], 50)
        assert sorted(c.candidate_id for c in chosen) == sorted(c.candidate_id for c in pool()[:5])

    def test_same_inputs_same_batch_and_another_seed_another_one(self) -> None:
        ids = lambda seed: [c.candidate_id for c in batch.pick_batch(pool(), 24, seed=seed)]  # noqa: E731
        assert ids(0) == ids(0) and ids(0) != ids(1)

    def test_the_order_mixes_activities(self) -> None:
        first = [c.activity for c in batch.pick_batch(pool(), 30)[:8]]
        assert len(set(first)) >= 3

    def test_a_batch_of_nothing_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            batch.pick_batch(pool(), 0)


class TestSplit:
    def split(self, size: int = 24, overlap: int = 8, names=("kuldeep", "pankaj")):
        return batch.split_batch(batch.pick_batch(pool(), size), names, overlap=overlap)

    def test_both_label_the_shared_ones_and_each_labels_their_own(self) -> None:
        a = self.split()
        k = {c.candidate_id for c in a.for_annotator("kuldeep")}
        p = {c.candidate_id for c in a.for_annotator("pankaj")}
        assert len(a.shared) == 8
        assert k & p == {c.candidate_id for c in a.shared}
        assert len(k) == len(p) == 8 + 8 and len(k | p) == 24

    def test_nothing_is_lost_or_given_twice(self) -> None:
        a = self.split(size=25, overlap=7)
        every = [c.candidate_id for c in a.shared] + [
            c.candidate_id for own in a.own.values() for c in own
        ]
        assert len(every) == len(set(every)) == 25

    def test_the_shared_clips_are_spread_evenly_through_the_batch(self) -> None:
        chosen = batch.pick_batch(pool(), 24)
        a = batch.split_batch(chosen, ("kuldeep", "pankaj"), overlap=8)
        positions = [i for i, c in enumerate(chosen) if c in a.shared]
        assert positions == [1, 4, 7, 10, 13, 16, 19, 22]

    def test_the_shared_clips_cover_the_activities_not_just_one(self) -> None:
        assert len(kinds(self.split(size=40, overlap=12).shared)) >= 3

    def test_the_order_differs_per_annotator_but_is_repeatable(self) -> None:
        a = self.split()
        order = lambda n: [c.candidate_id for c in a.for_annotator(n)]  # noqa: E731
        assert order("kuldeep") == order("kuldeep")
        shared = {c.candidate_id for c in a.shared}
        assert [i for i in order("kuldeep") if i in shared] != [
            i for i in order("pankaj") if i in shared
        ]

    def test_overlap_zero_is_allowed_and_overlap_everything_is_too(self) -> None:
        assert self.split(overlap=0).shared == ()
        assert len(self.split(size=10, overlap=10).shared) == 10

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"overlap": 99}, "overlap must be"),
            ({"overlap": -1}, "overlap must be"),
            ({"names": ("kuldeep",), "overlap": 4}, "at least two"),
            ({"names": ("kuldeep", "kuldeep")}, "each annotator once"),
            ({"names": ("Kuldeep P",)}, "lower-case"),
            ({"names": ()}, "each annotator once"),
        ],
    )
    def test_refuses_what_cannot_work(self, kwargs: dict, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            self.split(**kwargs)

    def test_one_annotator_with_no_overlap_gets_everything(self) -> None:
        a = self.split(names=("kuldeep",), overlap=0)
        assert len(a.for_annotator("kuldeep")) == 24


class TestCommand:
    def run(self, tmp_path: Path, *extra: str) -> Path:
        source = tmp_path / "candidates.json"
        write_candidates(pool(), source)
        out = tmp_path / "batch"
        args = ["phase-batch", str(source), "--out-dir", str(out), "--size", "24", "--overlap", "8"]
        assert main([*args, "--annotator", "kuldeep", "--annotator", "pankaj", *extra]) == 0
        return out

    def test_writes_the_union_and_one_file_each(self, tmp_path: Path) -> None:
        out = self.run(tmp_path)
        assert sorted(p.name for p in out.iterdir()) == ["all.json", "kuldeep.json", "pankaj.json"]
        everyone = {c.candidate_id for c in read_candidates(out / "all.json")}
        k = {c.candidate_id for c in read_candidates(out / "kuldeep.json")}
        p = {c.candidate_id for c in read_candidates(out / "pankaj.json")}
        assert len(everyone) == 24 and k | p == everyone and len(k & p) == 8

    def test_prints_what_is_in_the_batch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.run(tmp_path)
        text = capsys.readouterr().out
        assert "24 clips: 8 labelled by everyone, 8 only by kuldeep, 8 only by pankaj" in text
        assert (
            "| person_steals_object | 3 |" in text and "| kuldeep | 16 | 16 with 2 views |" in text
        )

    def test_the_files_are_valid_candidates(self, tmp_path: Path) -> None:
        out = self.run(tmp_path, "--seed", "3")
        assert isinstance(json.loads((out / "all.json").read_text()), list)


def long_cand(n: int, seconds: float, activity: str = "vehicle_drops_off_person") -> PhaseCandidate:
    base = cand(n, activity)
    return base.model_copy(
        update={"views": [v.model_copy(update={"end_s": v.start_s + seconds}) for v in base.views]}
    )


class TestDurationLimit:
    def pool(self) -> list[PhaseCandidate]:
        return [long_cand(i, 30.0) for i in range(10)] + [
            long_cand(100 + i, 60.0) for i in range(10)
        ]

    def test_clips_over_the_limit_are_never_chosen(self) -> None:
        chosen = batch.pick_batch(self.pool(), 15, max_duration_s=40)
        assert len(chosen) == 10 and all(c.duration_s <= 40 for c in chosen)

    def test_a_clip_exactly_at_the_limit_is_allowed(self) -> None:
        chosen = batch.pick_batch([long_cand(1, 40.0)], 5, max_duration_s=40)
        assert len(chosen) == 1

    def test_no_limit_means_every_clip_is_a_candidate(self) -> None:
        assert len(batch.pick_batch(self.pool(), 15)) == 15

    def test_a_rare_activity_that_is_too_long_is_left_out_too(self) -> None:
        pool = [
            long_cand(1, 90.0, "person_steals_object"),
            *[long_cand(i, 30.0) for i in range(5, 10)],
        ]
        chosen = batch.pick_batch(pool, 10, max_duration_s=40)
        assert "person_steals_object" not in kinds(chosen)

    def test_it_counts_what_the_limit_leaves_out(self) -> None:
        assert batch.too_long(self.pool(), 40) == 10
        assert batch.too_long(self.pool(), None) == 0
        assert batch.too_long(self.pool(), 60) == 0


class TestDurationLimitFromTheCommand:
    def run(self, tmp_path: Path, *extra: str) -> str:
        source = tmp_path / "candidates.json"
        write_candidates(
            [long_cand(i, 30.0) for i in range(8)] + [long_cand(50 + i, 80.0) for i in range(8)],
            source,
        )
        main(
            [
                "phase-batch",
                str(source),
                "--out-dir",
                str(tmp_path / "b"),
                "--size",
                "16",
                "--overlap",
                "0",
                "--annotator",
                "a",
                *extra,
            ]
        )
        return " ".join(c.candidate_id for c in read_candidates(tmp_path / "b" / "a.json"))

    def test_by_default_clips_too_long_for_the_timeline_are_left_out_and_said_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ids = self.run(tmp_path)
        assert len(ids.split()) == 8 and "-050" not in ids
        assert (
            "8 of 16 candidates were left out for being longer than 40 s" in capsys.readouterr().out
        )

    def test_zero_means_no_limit(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert len(self.run(tmp_path, "--max-duration", "0").split()) == 16
        assert "left out" not in capsys.readouterr().out
