"""MEVA extraction, against fixtures in the real published formats (written by hand, not copied)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from annotation_kit.meva import (
    DEFAULT_ACTIVITIES,
    Activity,
    MevaConfig,
    load_selection,
    parse_clip_name,
    read_activities,
    read_clip_table,
    select_candidates,
    summarise,
    sync_groups,
)

# ---- a small world: one camera set of three cameras, plus clips that cannot be aligned ----------
#
# A is the reference clip of set 3-420; B and C are synchronised to it. Frame f of B is frame
# f + 120 of A; frame f of C is frame f - 30 of A. All are five minutes (9000 frames at 30 fps).

A = "2018-03-05.09-50-00.09-55-00.school.G420"
B = "2018-03-05.09-50-00.09-55-00.school.G419"
C = "2018-03-05.09-50-00.09-55-00.school.G424"
IR = "2018-03-05.09-50-00.09-55-00.school.G510"
G999 = "2018-03-05.09-50-00.09-55-00.school.G999"
NO_OFFSET = "2018-03-05.09-50-00.09-55-00.school.G511"
SLOT = "2018-03-05.09-50-00"

TABLE = f"""\
{A} {SLOT} no-camera-model 3-420 self 0 0
{B} {SLOT} no-camera-model 3-420 {A} 120 30
{C} {SLOT} no-camera-model 3-420 {A} -30 30
{IR} {SLOT} no-camera-model IR no-reference-clip 0 -1
{NO_OFFSET} {SLOT} no-camera-model 3-420 {A} 0 -1
this line is not a clip table row
{G999} {SLOT} no-camera-model skip no-reference-clip-available 0 -1
"""


def act(
    name: str = "vehicle_drops_off_person",
    *,
    start: int,
    end: int,
    id2: int = 1,
    status: str = "good",
    actors: int = 2,
    style: str = "act2",
) -> Activity:  # noqa: PLR0913
    return Activity(name, id2, start, end, status, actors)


@pytest.fixture
def table(tmp_path: Path):  # noqa: ANN201
    path = tmp_path / "meva-clip-camera-and-time-table.txt"
    path.write_text(TABLE)
    return read_clip_table(path)


class TestClipNames:
    def test_reads_date_times_site_and_camera(self) -> None:
        parsed = parse_clip_name(A)
        assert parsed == {
            "date": "2018-03-05",
            "start_s": 9 * 3600 + 50 * 60,
            "end_s": 9 * 3600 + 55 * 60,
            "site": "school",
            "camera": "G420",
        }

    def test_a_clip_that_runs_past_midnight_ends_after_it_starts(self) -> None:
        parsed = parse_clip_name("2018-03-05.23-58-00.00-03-00.admin.G326")
        assert parsed is not None and parsed["end_s"] == 86400 + 3 * 60

    @pytest.mark.parametrize(
        "name", ["", "not-a-clip", "2018-03-05.09-50-00.school.G420", A + ".avi"]
    )
    def test_a_name_that_is_not_a_clip_is_none(self, name: str) -> None:
        assert parse_clip_name(name) is None


class TestClipTable:
    def test_reads_the_seven_fields(self, table) -> None:  # noqa: ANN001
        b = table[B]
        assert (b.slot, b.camera_set, b.reference, b.offset, b.precision) == (
            SLOT,
            "3-420",
            A,
            120,
            30,
        )
        assert (b.camera, b.site, b.frames) == ("G419", "school", 9000)

    def test_a_reference_clip_is_its_own_reference_with_no_offset(self, table) -> None:  # noqa: ANN001
        assert table[A].reference == A and table[A].offset == 0

    def test_a_negative_offset(self, table) -> None:  # noqa: ANN001
        assert table[C].offset == -30

    def test_a_clip_with_no_reference_has_none(self, table) -> None:  # noqa: ANN001
        assert table[IR].reference is None
        assert table[G999].reference is None  # the long spelling

    def test_skips_lines_that_are_not_rows(self, table) -> None:  # noqa: ANN001
        assert len(table) == 6  # 5 real rows plus the G999 one; the stray line is dropped

    def test_which_clips_can_be_aligned(self, table) -> None:  # noqa: ANN001
        assert table[A].synchronised and table[B].synchronised and table[C].synchronised
        assert not table[IR].synchronised  # infra-red cameras are not in a camera set yet
        assert not table[NO_OFFSET].synchronised  # precision -1: no offset available

    def test_groups_hold_clips_that_show_the_same_moment(self, table) -> None:  # noqa: ANN001
        groups = sync_groups(table)
        assert list(groups) == [("3-420", A)]
        assert {c.camera for c in groups[("3-420", A)]} == {"G420", "G419", "G424"}

    def test_a_clip_without_a_reference_has_no_group(self, table) -> None:  # noqa: ANN001
        with pytest.raises(ValueError, match="no reference clip"):
            _ = table[IR].group


class TestReadingActivities:
    def write(self, tmp_path: Path, text: str) -> Path:
        path = tmp_path / "x.activities.yml"
        path.write_text(text)
        return path

    def test_the_act3_style_of_the_bucket_examples(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            '- { meta: "clip events" }\n'
            '- { meta: "Open_Trunk 1 instances" }\n'
            "- { act: { act3: { Open_Trunk: 1.0 } , id2: 1, timespan: [{tsr0: [2050, 2247]}], "
            "src: truth, actors: [{ id1: 0, timespan: [{tsr0: [2050, 2247]}]}  , "
            "{ id1: 1, timespan: [{tsr0: [2050, 2247]}]}  ]} }\n",
        )
        assert read_activities(path) == [Activity("Open_Trunk", 1, 2050, 2247, "truth", 2)]

    def test_the_act2_quoted_style_of_the_annotation_repo(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            "- {'act': {'act2': {'person_carries_heavy_object': 1.0}, 'actors': [{'id1': 201, "
            "'timespan': [{'tsr0': [7437, 7684]}]}], 'id2': 119, 'src_status': 'good', "
            "'timespan': [{'tsr0': [7431, 7837]}]}}\n",
        )
        assert read_activities(path) == [
            Activity("person_carries_heavy_object", 119, 7431, 7837, "good", 1)
        ]

    def test_takes_the_most_confident_name(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            "- {act: {act2: {person_sits_down: 0.2, person_stands_up: 0.8}, id2: 3, "
            "timespan: [{tsr0: [10, 20]}], src_status: good, actors: []}}\n",
        )
        assert read_activities(path)[0].name == "person_stands_up"

    def test_several_timespans_cover_from_the_first_frame_to_the_last(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            "- {act: {act2: {x_y: 1.0}, id2: 4, timespan: [{tsr0: [100, 200]}, {tsr0: [50, 80]}], "
            "src_status: good, actors: []}}\n",
        )
        activity = read_activities(path)[0]
        assert (activity.start_frame, activity.end_frame) == (50, 200)

    def test_a_status_may_be_called_src_or_be_missing(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            "- {act: {act2: {a_b: 1.0}, id2: 1, timespan: [{tsr0: [1, 2]}], src: truth, "
            "actors: []}}\n"
            "- {act: {act2: {a_b: 1.0}, id2: 2, timespan: [{tsr0: [1, 2]}], actors: []}}\n",
        )
        assert [a.status for a in read_activities(path)] == ["truth", "unknown"]

    def test_ignores_what_is_not_an_activity_with_a_name_and_a_span(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            "- {meta: hello}\n- 5\n- {act: {id2: 1, timespan: [{tsr0: [1, 2]}]}}\n"
            "- {act: {act2: {a_b: 1.0}, id2: 2}}\n- {types: {id1: 0}}\n",
        )
        assert read_activities(path) == []

    def test_an_empty_file_has_no_activities(self, tmp_path: Path) -> None:
        assert read_activities(self.write(tmp_path, "")) == []


class TestAligningViews:
    """The arithmetic that makes every view show the same moment."""

    def candidates(self, table, activities, **config):  # noqa: ANN001, ANN003, ANN201
        return select_candidates(
            {A: activities}, table, MevaConfig(per_activity_cap=None, per_slot_cap=None, **config)
        )

    def test_every_view_is_cut_to_the_same_moment_in_its_own_time(self, table) -> None:  # noqa: ANN001
        # The drop-off is frames 3000-3600 of A (100 s to 120 s); with 10 s either side the window
        # is reference frames 2700-3900. B's frame f is A's f + 120, so B's window is 2580-3780
        # (86 s
        # to 126 s); C's frame f is A's f - 30, so C's is 2730-3930 (91 s to 131 s).
        selection = self.candidates(table, [act(start=3000, end=3600)])
        assert len(selection.candidates) == 1
        views = {v.camera: (v.start_s, v.end_s) for v in selection.candidates[0].views}
        assert views == {"G420": (90.0, 130.0), "G419": (86.0, 126.0), "G424": (91.0, 131.0)}

    def test_all_the_views_have_the_same_length(self, table) -> None:  # noqa: ANN001
        candidate = self.candidates(table, [act(start=3000, end=3600)]).candidates[0]
        assert {round(v.end_s - v.start_s, 3) for v in candidate.views} == {40.0}
        assert candidate.duration_s == 40.0

    def test_the_view_the_activity_was_annotated_in_comes_first(self, table) -> None:  # noqa: ANN001
        candidate = self.candidates(table, [act(start=3000, end=3600)]).candidates[0]
        assert candidate.primary_view == "G420"
        assert [v.camera for v in candidate.views] == ["G420", "G419", "G424"]

    def test_padding_is_configurable(self, table) -> None:  # noqa: ANN001
        candidate = self.candidates(
            table, [act(start=3000, end=3600)], pad_before_s=2, pad_after_s=4
        ).candidates[0]
        a = next(v for v in candidate.views if v.camera == "G420")
        assert (a.start_s, a.end_s) == (98.0, 124.0)

    def test_a_view_that_starts_too_late_to_see_the_window_is_left_out(self, table) -> None:  # noqa: ANN001
        # B's frame f is A's frame f + 120, so B only starts at A's frame 120. Activity at A frames
        # 200-350 with 3 s before it: the window starts at reference frame 110, before B exists.
        selection = self.candidates(table, [act(start=200, end=350)], pad_before_s=3)
        assert {v.camera for v in selection.candidates[0].views} == {"G420", "G424"}

    def test_a_view_that_ends_before_the_window_does_is_left_out(self, table) -> None:  # noqa: ANN001
        # C's frame f is A's frame f - 30, so C ends at A's frame 8970. Activity at A frames
        # 8600-8800 with 6 s after it: the window ends at 8980, after C has stopped but not A or B.
        selection = self.candidates(table, [act(start=8600, end=8800)], pad_after_s=6)
        assert {v.camera for v in selection.candidates[0].views} == {"G420", "G419"}

    def test_if_the_annotated_view_is_left_out_another_becomes_primary(self, table) -> None:  # noqa: ANN001
        # Annotated in C at its frames 8800-8850 (reference 8770-8820); 6 s after is reference 9000:
        # C ends at 8970, so C cannot see the window while A and B can.
        cfg = MevaConfig(per_activity_cap=None, per_slot_cap=None, pad_after_s=6)
        candidate = select_candidates({C: [act(start=8800, end=8850)]}, table, cfg).candidates[0]
        assert {v.camera for v in candidate.views} == {"G420", "G419"}
        assert candidate.primary_view == candidate.views[0].camera
        assert candidate.primary_view != "G424"

    def test_too_few_views_is_a_reason_not_a_crash(self, table) -> None:  # noqa: ANN001
        selection = self.candidates(table, [act(start=3000, end=3600)], min_views=4)
        assert selection.candidates == []
        assert selection.skipped["too_few_views"] == 1

    def test_one_view_is_allowed_if_asked_for(self, table) -> None:  # noqa: ANN001
        selection = self.candidates(table, [act(start=3000, end=3600)], min_views=1)
        assert len(selection.candidates) == 1


class TestWhatIsSelected:
    def pick(self, table, activities, **config):  # noqa: ANN001, ANN003, ANN201
        return select_candidates(
            {A: activities}, table, MevaConfig(per_activity_cap=None, per_slot_cap=None, **config)
        )

    def test_only_the_wanted_activities_are_counted(self, table) -> None:  # noqa: ANN001
        selection = self.pick(
            table, [act("person_talks_to_person", start=3000, end=3600), act(start=3000, end=3600)]
        )
        assert selection.seen == {"vehicle_drops_off_person": 1}
        assert len(selection.candidates) == 1

    def test_the_candidate_says_where_it_is_from(self, table) -> None:  # noqa: ANN001
        candidate = self.pick(table, [act(start=3000, end=3600, id2=7)]).candidates[0]
        assert candidate.candidate_id == f"meva:{A}:vehicle_drops_off_person:7"
        assert candidate.dataset == "meva" and candidate.activity == "vehicle_drops_off_person"
        assert candidate.source_video == f"meva:3-420:{SLOT}"
        assert "3 synchronised views" in (candidate.note or "")

    def test_the_two_event_types_meva_has_are_named_and_the_rest_are_activities(
        self, table
    ) -> None:  # noqa: ANN001
        names = ("person_abandons_package", "person_steals_object", "vehicle_drops_off_person")
        selection = self.pick(
            table,
            [
                act(n, start=3000 + 1000 * i, end=3600 + 1000 * i, id2=i)
                for i, n in enumerate(names)
            ],
        )
        types = {c.activity: c.event_type for c in selection.candidates}
        assert types == {
            "person_abandons_package": "abandoned_object",
            "person_steals_object": "theft",
            "vehicle_drops_off_person": "activity",
        }

    def test_the_event_type_mapping_is_configurable(self, table) -> None:  # noqa: ANN001
        selection = self.pick(
            table,
            [act(start=3000, end=3600)],
            event_types={"vehicle_drops_off_person": "pickup_dropoff"},
        )
        assert selection.candidates[0].event_type == "pickup_dropoff"

    def test_the_default_activities_include_the_rare_incident_ones(self) -> None:
        assert {"person_abandons_package", "person_steals_object"} <= set(DEFAULT_ACTIVITIES)
        assert "person_talks_to_person" not in DEFAULT_ACTIVITIES  # too common and too static

    @pytest.mark.parametrize(
        ("activity", "reason"),
        [
            (act(start=3000, end=3600, status="not_good"), "annotation_not_good"),
            (act(start=3000, end=3600, status="unaudited"), "annotation_not_good"),
            (act(start=3000, end=3020), "activity_too_short"),  # 0.67 s
            (act(start=100, end=6000), "window_too_long"),  # 197 s + 20 s of padding
        ],
    )
    def test_what_is_left_out_is_counted_by_reason(self, table, activity, reason) -> None:  # noqa: ANN001
        selection = self.pick(table, [activity])
        assert selection.candidates == [] and selection.skipped[reason] == 1

    def test_other_statuses_are_kept(self, table) -> None:  # noqa: ANN001
        for status in ("good", "truth", "janitor", "gladiator_1", "unknown"):
            assert len(self.pick(table, [act(start=3000, end=3600, status=status)]).candidates) == 1

    def test_a_clip_that_cannot_be_aligned_is_counted(self, table) -> None:  # noqa: ANN001
        selection = select_candidates(
            {IR: [act(start=3000, end=3600)], NO_OFFSET: [act(start=3000, end=3600)]},
            table,
            MevaConfig(),
        )
        assert selection.skipped["not_synchronised"] == 2 and selection.candidates == []

    def test_a_clip_that_is_not_in_the_table_is_counted(self, table) -> None:  # noqa: ANN001
        selection = select_candidates(
            {"2018-03-05.10-00-00.10-05-00.school.G420": [act(start=3000, end=3600)]},
            table,
            MevaConfig(),
        )
        assert selection.skipped["clip_not_in_table"] == 1

    def test_the_boundaries_of_length_are_inclusive(self, table) -> None:  # noqa: ANN001
        assert len(self.pick(table, [act(start=3000, end=3030)]).candidates) == 1  # exactly 1.0 s
        # 70 s of activity + 20 s of padding = exactly the 90 s maximum
        assert len(self.pick(table, [act(start=3000, end=3000 + 70 * 30)]).candidates) == 1
        assert (
            self.pick(table, [act(start=3000, end=3000 + 71 * 30)]).skipped["window_too_long"] == 1
        )


class TestTheSameActivityInSeveralViews:
    """MEVA annotates an activity in every clip that sees it: that is one episode, not three."""

    def pick(self, table, by_clip, **config):  # noqa: ANN001, ANN003, ANN201
        return select_candidates(
            by_clip, table, MevaConfig(per_activity_cap=None, per_slot_cap=None, **config)
        )

    def test_overlapping_instances_of_one_activity_are_one_candidate(self, table) -> None:  # noqa: ANN001
        # A frames 3000-3600 are B frames 2880-3480 and C frames 3030-3630.
        selection = self.pick(
            table,
            {
                A: [act(start=3000, end=3600, id2=1, actors=2)],
                B: [act(start=2880, end=3480, id2=1, actors=3)],
                C: [act(start=3030, end=3630, id2=1, actors=1)],
            },
        )
        assert len(selection.candidates) == 1
        assert selection.seen["vehicle_drops_off_person"] == 3

    def test_the_view_with_the_most_people_marked_is_the_primary_one(self, table) -> None:  # noqa: ANN001
        selection = self.pick(
            table,
            {
                A: [act(start=3000, end=3600, actors=2)],
                B: [act(start=2880, end=3480, actors=5)],
                C: [act(start=3030, end=3630, actors=1)],
            },
        )
        assert selection.candidates[0].primary_view == "G419"
        assert selection.candidates[0].candidate_id.startswith(f"meva:{B}:")

    def test_the_same_activity_at_another_time_is_another_candidate(self, table) -> None:  # noqa: ANN001
        selection = self.pick(
            table, {A: [act(start=1000, end=1300, id2=1), act(start=5000, end=5300, id2=2)]}
        )
        assert len(selection.candidates) == 2

    def test_a_different_activity_at_the_same_time_is_another_candidate(self, table) -> None:  # noqa: ANN001
        selection = self.pick(
            table,
            {
                A: [
                    act(start=3000, end=3600),
                    act("vehicle_picks_up_person", start=3000, end=3600, id2=2),
                ]
            },
        )
        assert len(selection.candidates) == 2

    def test_a_brush_of_overlap_is_not_the_same_activity(self, table) -> None:  # noqa: ANN001
        selection = self.pick(
            table, {A: [act(start=1000, end=1300, id2=1), act(start=1290, end=1590, id2=2)]}
        )
        assert len(selection.candidates) == 2


class TestLimitingTheSelection:
    def many(self, table):  # noqa: ANN001, ANN201
        activities = [act(start=500 * i, end=500 * i + 200, id2=i) for i in range(1, 12)]
        return {A: activities}

    def pick(self, table, **config):  # noqa: ANN001, ANN003, ANN201
        return select_candidates(self.many(table), table, MevaConfig(**config))

    def test_a_cap_per_activity_keeps_that_many(self, table) -> None:  # noqa: ANN001
        selection = self.pick(table, per_slot_cap=None, per_activity_cap=4)
        assert len(selection.candidates) == 4

    def test_a_cap_per_slot_keeps_that_many_from_one_scene(self, table) -> None:  # noqa: ANN001
        selection = self.pick(table, per_slot_cap=3, per_activity_cap=None)
        assert len(selection.candidates) == 3

    def test_with_no_caps_everything_is_kept(self, table) -> None:  # noqa: ANN001
        assert len(self.pick(table, per_slot_cap=None, per_activity_cap=None).candidates) == 11

    def test_the_same_seed_gives_the_same_selection_and_another_seed_another(self, table) -> None:  # noqa: ANN001
        def ids(seed: int) -> list[str]:
            selection = self.pick(table, per_slot_cap=None, per_activity_cap=4, seed=seed)
            return [c.candidate_id for c in selection.candidates]

        assert ids(1) == ids(1)
        assert ids(1) != ids(2)

    def test_a_capped_selection_is_a_subset_of_the_full_one(self, table) -> None:  # noqa: ANN001
        full = {
            c.candidate_id
            for c in self.pick(table, per_slot_cap=None, per_activity_cap=None).candidates
        }
        capped = {
            c.candidate_id
            for c in self.pick(table, per_slot_cap=None, per_activity_cap=5).candidates
        }
        assert capped <= full and len(capped) == 5

    def test_the_defaults_are_capped_per_slot_and_per_activity(self) -> None:
        config = MevaConfig()
        assert (config.per_slot_cap, config.per_activity_cap) == (3, 60)

    def test_candidates_come_out_in_a_stable_order(self, table) -> None:  # noqa: ANN001
        ids = [
            c.candidate_id
            for c in self.pick(table, per_slot_cap=None, per_activity_cap=None).candidates
        ]
        assert ids == sorted(ids)


class TestWhereTheVideosAre:
    def test_a_clip_is_filed_under_the_hour_it_ends_in(self, table) -> None:  # noqa: ANN001
        candidate = select_candidates(
            {A: [act(start=3000, end=3600)]}, table, MevaConfig()
        ).candidates[0]
        by_camera = {v.camera: v.source_uri for v in candidate.views}
        # 09-50-00.09-55-00 ends in hour 09
        assert (
            by_camera["G420"] == f"s3://mevadata-public-01/drops-123-r13/2018-03-05/09/{A}.r13.avi"
        )

    def test_a_clip_that_ends_on_the_hour_is_filed_under_that_hour(self, tmp_path: Path) -> None:
        path = tmp_path / "t.txt"
        g420 = "2018-03-05.09-55-00.10-00-00.school.G420"
        g419 = "2018-03-05.09-55-00.10-00-00.school.G419"
        path.write_text(
            f"{g420} 2018-03-05.09-55-00 x 3-420 self 0 0\n"
            f"{g419} 2018-03-05.09-55-00 x 3-420 {g420} 0 0\n"
        )
        table = read_clip_table(path)
        name = "2018-03-05.09-55-00.10-00-00.school.G420"
        candidate = select_candidates(
            {name: [act(start=3000, end=3600)]}, table, MevaConfig()
        ).candidates[0]
        assert "/2018-03-05/10/" in candidate.views[0].source_uri

    def test_the_prefix_is_configurable(self, table) -> None:  # noqa: ANN001
        config = MevaConfig(s3_prefix="s3://elsewhere/meva/")
        candidate = select_candidates({A: [act(start=3000, end=3600)]}, table, config).candidates[0]
        assert candidate.views[0].source_uri.startswith("s3://elsewhere/meva/2018-03-05/")


class TestLoadingARepoCheckout:
    def write_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "metadata").mkdir()
        (tmp_path / "metadata/meva-clip-camera-and-time-table.txt").write_text(TABLE)
        folder = tmp_path / "annotation/DIVA-phase-2/MEVA/kitware/2018-03-05/09"
        folder.mkdir(parents=True)
        (folder / f"{A}.activities.yml").write_text(
            "- {act: {act2: {vehicle_drops_off_person: 1.0}, id2: 1, "
            "timespan: [{tsr0: [3000, 3600]}], src_status: good, actors: [{id1: 1}, {id1: 2}]}}\n"
        )
        (folder / "2018-03-05.09-50-00.09-55-00.school.G777.activities.yml").write_text(
            "- {act: {act2: {vehicle_drops_off_person: 1.0}, id2: 1, "
            "timespan: [{tsr0: [3000, 3600]}]}}\n"
        )
        return tmp_path

    def test_reads_the_table_and_the_annotation_files(self, tmp_path: Path) -> None:
        selection = load_selection(
            self.write_repo(tmp_path), MevaConfig(per_slot_cap=None, per_activity_cap=None)
        )
        assert [c.candidate_id for c in selection.candidates] == [
            f"meva:{A}:vehicle_drops_off_person:1"
        ]

    def test_annotations_for_a_clip_not_in_the_table_are_ignored(self, tmp_path: Path) -> None:
        selection = load_selection(self.write_repo(tmp_path))
        assert selection.seen["vehicle_drops_off_person"] == 1  # the G777 file was not even read


class TestSummary:
    def test_lists_activities_by_how_many_there_were_and_what_was_left_out(self, table) -> None:  # noqa: ANN001
        selection = select_candidates(
            {A: [act(start=3000, end=3600), act(start=100, end=6000, id2=2, status="good")]},
            table,
            MevaConfig(),
        )
        text = summarise(selection)
        assert "| vehicle_drops_off_person | 2 | 1 |" in text
        assert "| **all** | 2 | 1 |" in text
        assert "Left out: 1 window_too_long" in text

    def test_says_nothing_about_what_was_not_left_out(self, table) -> None:  # noqa: ANN001
        text = summarise(select_candidates({A: [act(start=3000, end=3600)]}, table, MevaConfig()))
        assert "Left out" not in text


@pytest.mark.skipif(
    not os.environ.get("MEVA_REPO"), reason="needs a checkout of the MEVA annotation repo"
)
def test_on_the_real_annotations_the_defaults_give_enough_candidates() -> None:
    """Run with MEVA_REPO=<checkout of gitlab.kitware.com/meva/meva-data-repo>.

    On the 2,212 kitware and kitware-meva-training annotation files: 361 candidates from 179
    five-minute slots, the target being at least 250.
    """
    selection = load_selection(os.environ["MEVA_REPO"])
    assert len(selection.candidates) >= 250
    assert all(len(c.views) >= 2 for c in selection.candidates)


class TestEdgesOfTheFormats:
    def test_a_clip_whose_start_and_end_are_the_same_instant_is_zero_length_not_a_day(self) -> None:
        parsed = parse_clip_name("2018-03-05.09-50-00.09-50-00.school.G420")
        assert parsed is not None and parsed["end_s"] == parsed["start_s"]

    def test_when_both_status_fields_are_present_src_status_wins(self, tmp_path: Path) -> None:
        path = tmp_path / "x.activities.yml"
        path.write_text(
            "- {act: {act2: {a_b: 1.0}, id2: 1, timespan: [{tsr0: [1, 2]}], "
            "src_status: good, src: truth, actors: []}}\n"
        )
        assert read_activities(path)[0].status == "good"


class TestMergingTheSameActivity:
    """Instances of one activity in different views are one episode when they overlap enough."""

    def pick(self, table, by_clip):  # noqa: ANN001, ANN201
        return select_candidates(
            by_clip, table, MevaConfig(per_activity_cap=None, per_slot_cap=None)
        )

    def test_instances_that_overlap_by_half_are_the_same_episode(self, table) -> None:  # noqa: ANN001
        # B's 2880-3480 is the same moment as A's 3000-3600; 150 frames later, the overlap is
        # 450 of 750 frames (IoU 0.6)
        shifted = {A: [act(start=3000, end=3600)], B: [act(start=2880 + 150, end=3480 + 150)]}
        assert len(self.pick(table, shifted).candidates) == 1

    def test_instances_that_overlap_by_a_fifth_are_two_episodes(self, table) -> None:  # noqa: ANN001
        apart = {
            A: [act(start=3000, end=3600)],
            B: [act(start=2880 + 480, end=3480 + 480)],
        }  # IoU 120/1080
        assert len(self.pick(table, apart).candidates) == 2


class TestCapsAcrossActivities:
    def test_the_slot_cap_counts_candidates_of_every_activity_together(self, table) -> None:  # noqa: ANN001
        activities = [
            act("vehicle_drops_off_person", start=1000, end=1300, id2=1),
            act("vehicle_picks_up_person", start=3000, end=3300, id2=2),
            act("person_embraces_person", start=5000, end=5300, id2=3),
        ]
        capped = select_candidates(
            {A: activities}, table, MevaConfig(per_slot_cap=1, per_activity_cap=None)
        )
        assert len(capped.candidates) == 1  # one scene: three activities share it
        free = select_candidates(
            {A: activities}, table, MevaConfig(per_slot_cap=None, per_activity_cap=None)
        )
        assert len(free.candidates) == 3


class TestTheSummaryOrder:
    def test_the_most_common_activity_is_listed_first(self, table) -> None:  # noqa: ANN001
        activities = [
            act("person_embraces_person", start=1000, end=1300, id2=1),
            act("vehicle_drops_off_person", start=3000, end=3300, id2=2),
            act("vehicle_drops_off_person", start=5000, end=5300, id2=3),
        ]
        text = summarise(
            select_candidates(
                {A: activities}, table, MevaConfig(per_slot_cap=None, per_activity_cap=None)
            )
        )
        assert text.index("vehicle_drops_off_person") < text.index("person_embraces_person")
