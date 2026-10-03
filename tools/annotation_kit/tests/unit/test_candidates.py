from __future__ import annotations

import pytest
from annotation_kit.candidates import (
    FPS,
    PhaseCandidate,
    ViewSpec,
    clip_relpath,
    clip_uri,
    cut_command,
    safe_id,
)
from pydantic import ValidationError


def view(
    camera: str = "G420", start: float = 10, end: float = 50, uri: str = "s3://b/a.avi"
) -> ViewSpec:
    return ViewSpec(camera=camera, source_uri=uri, start_s=start, end_s=end)


def candidate(**over) -> PhaseCandidate:  # noqa: ANN003
    fields = {
        "candidate_id": "meva:clip-1:act:7",
        "dataset": "meva",
        "source_video": "meva:3-420:slot",
        "event_type": "activity",
        "primary_view": "G420",
        "views": [view("G420"), view("G419", 20, 60)],
    }
    fields.update(over)
    return PhaseCandidate(**fields)


class TestViewSpec:
    def test_must_end_after_it_starts(self) -> None:
        with pytest.raises(ValidationError, match="end_s must be after start_s"):
            view(start=5, end=5)
        with pytest.raises(ValidationError):
            view(start=-1, end=5)

    def test_has_a_duration(self) -> None:
        assert view(start=10, end=50).duration_s == 40


class TestPhaseCandidate:
    def test_a_valid_candidate_has_the_duration_of_its_views(self) -> None:
        assert candidate().duration_s == 40

    def test_the_primary_view_must_be_one_of_the_views(self) -> None:
        with pytest.raises(ValidationError, match="primary_view is not one of the views"):
            candidate(primary_view="G999")

    def test_a_camera_may_appear_once(self) -> None:
        with pytest.raises(ValidationError, match="appears twice"):
            candidate(views=[view("G420"), view("G420", 20, 60)])

    def test_all_views_must_be_cut_to_the_same_length(self) -> None:
        with pytest.raises(ValidationError, match="same length"):
            candidate(views=[view("G420", 10, 50), view("G419", 20, 70)])

    def test_a_hair_of_difference_in_length_is_tolerated(self) -> None:
        assert candidate(views=[view("G420", 10, 50), view("G419", 20, 60.04)])

    def test_needs_a_view(self) -> None:
        with pytest.raises(ValidationError):
            candidate(views=[])

    def test_only_known_datasets_and_no_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            candidate(dataset="youtube")
        with pytest.raises(ValidationError):
            candidate(mood="tense")

    def test_round_trips_through_json(self) -> None:
        original = candidate(note="3 views")
        assert PhaseCandidate.model_validate_json(original.model_dump_json()) == original


class TestNamingClips:
    def test_an_id_becomes_a_folder_name(self) -> None:
        assert safe_id("meva:2018-03-05.09-50-00.school.G420:vehicle_drops_off_person:9") == (
            "meva_2018-03-05.09-50-00.school.G420_vehicle_drops_off_person_9"
        )

    def test_unsafe_runs_collapse_and_the_ends_are_trimmed(self) -> None:
        assert safe_id(":a / b::c:") == "a_b_c"

    def test_a_cut_view_lives_in_its_candidates_folder_named_by_camera(self) -> None:
        c = candidate()
        assert clip_relpath(c, c.views[1]) == "meva_clip-1_act_7/G419.mp4"

    def test_the_uri_joins_a_prefix_with_or_without_a_trailing_slash(self) -> None:
        c = candidate()
        expected = "s3://vms-evidence/clips/meva_clip-1_act_7/G420.mp4"
        assert clip_uri("s3://vms-evidence/clips", c, c.views[0]) == expected
        assert clip_uri("s3://vms-evidence/clips/", c, c.views[0]) == expected


class TestCutting:
    def test_cuts_the_window_re_encoded_at_a_fixed_rate_with_a_keyframe_each_second(self) -> None:
        argv = cut_command(view("G420", 86.5, 126.5), "out/G420.mp4")
        assert argv[0] == "ffmpeg"
        assert argv[argv.index("-ss") + 1] == "86.500"
        assert argv[argv.index("-t") + 1] == "40.000"
        assert argv[argv.index("-r") + 1] == str(FPS) == "30"
        assert argv[argv.index("-g") + 1] == "30"
        assert argv[argv.index("-c:v") + 1] == "libx264"
        assert "-an" in argv and argv[-1] == "out/G420.mp4"

    def test_seeks_before_the_input_so_it_is_fast_and_the_re_encode_makes_it_exact(self) -> None:
        argv = cut_command(view(), "o.mp4")
        assert argv.index("-ss") < argv.index("-i")

    def test_reads_the_source_the_view_names(self) -> None:
        argv = cut_command(view(uri="s3://b/x.avi"), "o.mp4")
        assert argv[argv.index("-i") + 1] == "s3://b/x.avi"

    def test_a_resolver_can_turn_a_uri_into_a_local_path(self) -> None:
        argv = cut_command(
            view(uri="s3://b/x.avi"),
            "o.mp4",
            resolve_source=lambda u: u.replace("s3://b/", "/data/"),
        )
        assert argv[argv.index("-i") + 1] == "/data/x.avi"

    def test_overwrites_and_does_not_read_the_terminal(self) -> None:
        argv = cut_command(view(), "o.mp4")
        assert "-y" in argv and "-nostdin" in argv


class TestTolerance:
    def test_a_tenth_of_a_second_difference_in_length_is_refused_but_a_hair_is_not(self) -> None:
        with pytest.raises(ValidationError, match="same length"):
            candidate(views=[view("G420", 10, 50), view("G419", 20, 60.2)])
        assert candidate(views=[view("G420", 10, 50), view("G419", 20, 60.04)])
