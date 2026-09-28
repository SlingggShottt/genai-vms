"""Tests for perception.domain.twin_builder."""

from datetime import UTC, datetime, timedelta

import pytest
from perception.domain.twin_builder import build_twin
from vms_common.contracts.twin import Frame, FrameObject, ObjectAttributes

T0 = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)


def _frame(idx: int, ts_offset_s: float, objects: list[FrameObject]) -> Frame:
    return Frame(
        ts=T0 + timedelta(seconds=ts_offset_s),
        idx=idx,
        keyframe_uri=f"s3://vms-keyframes/cam01/{idx:04d}.jpg",
        objects=objects,
    )


def _person(track_id: str, *, zones: list[str] | None = None, upper: str = "red") -> FrameObject:
    return FrameObject(
        track_id=track_id,
        category="person",
        conf=0.9,
        bbox=(0.1, 0.1, 0.3, 0.3),
        attributes=ObjectAttributes(upper_color=upper, lower_color="black"),
        zones=zones or [],
    )


def test_build_twin_shapes_the_document() -> None:
    frames = [_frame(0, 0.0, [_person("cam01-t1")])]

    twin = build_twin(
        segment_id="cam01_seg",
        camera_id="cam01",
        site_id="site1",
        start_ts=T0,
        end_ts=T0 + timedelta(seconds=10),
        sample_fps=2.0,
        frame_size=(1920, 1080),
        frames=frames,
        best_crop_uris={"cam01-t1": "s3://vms-crops/cam01-t1.jpg"},
        embedding_indices={"cam01-t1": 0},
    )

    assert twin.schema_version == "twin.v1"
    assert twin.frame_size.w == 1920
    assert len(twin.tracks) == 1
    assert twin.tracks[0].track_id == "cam01-t1"


def test_track_dwell_spans_first_to_last_appearance() -> None:
    frames = [
        _frame(0, 0.0, [_person("cam01-t1")]),
        _frame(1, 4.0, [_person("cam01-t1")]),
        _frame(2, 9.5, [_person("cam01-t1")]),
    ]

    twin = build_twin(
        segment_id="s",
        camera_id="cam01",
        site_id="site1",
        start_ts=T0,
        end_ts=T0 + timedelta(seconds=10),
        sample_fps=2.0,
        frame_size=(100, 100),
        frames=frames,
        best_crop_uris={"cam01-t1": "s3://vms-crops/x.jpg"},
        embedding_indices={"cam01-t1": 0},
    )

    assert twin.tracks[0].dwell_s == pytest.approx(9.5)


def test_zones_visited_is_a_deduplicated_union_in_order() -> None:
    frames = [
        _frame(0, 0.0, [_person("cam01-t1", zones=["entrance"])]),
        _frame(1, 1.0, [_person("cam01-t1", zones=["entrance"])]),
        _frame(2, 2.0, [_person("cam01-t1", zones=["entrance", "lobby"])]),
    ]

    twin = build_twin(
        segment_id="s",
        camera_id="cam01",
        site_id="site1",
        start_ts=T0,
        end_ts=T0 + timedelta(seconds=10),
        sample_fps=2.0,
        frame_size=(100, 100),
        frames=frames,
        best_crop_uris={"cam01-t1": "s3://vms-crops/x.jpg"},
        embedding_indices={"cam01-t1": 0},
    )

    assert twin.tracks[0].zones_visited == ["entrance", "lobby"]


def test_attributes_summary_is_the_most_common_across_frames() -> None:
    frames = [
        _frame(0, 0.0, [_person("cam01-t1", upper="red")]),
        _frame(1, 1.0, [_person("cam01-t1", upper="red")]),
        _frame(2, 2.0, [_person("cam01-t1", upper="blue")]),
    ]

    twin = build_twin(
        segment_id="s",
        camera_id="cam01",
        site_id="site1",
        start_ts=T0,
        end_ts=T0 + timedelta(seconds=10),
        sample_fps=2.0,
        frame_size=(100, 100),
        frames=frames,
        best_crop_uris={"cam01-t1": "s3://vms-crops/x.jpg"},
        embedding_indices={"cam01-t1": 0},
    )

    assert twin.tracks[0].attributes_summary.upper_color == "red"


def test_scene_counts_are_the_per_frame_maximum() -> None:
    frames = [
        _frame(0, 0.0, [_person("cam01-t1"), _person("cam01-t2")]),
        _frame(1, 1.0, [_person("cam01-t1")]),
    ]

    twin = build_twin(
        segment_id="s",
        camera_id="cam01",
        site_id="site1",
        start_ts=T0,
        end_ts=T0 + timedelta(seconds=10),
        sample_fps=2.0,
        frame_size=(100, 100),
        frames=frames,
        best_crop_uris={"cam01-t1": "s3://vms-crops/1.jpg", "cam01-t2": "s3://vms-crops/2.jpg"},
        embedding_indices={"cam01-t1": 0, "cam01-t2": 1},
    )

    assert twin.scene.person_count_max == 2


def test_missing_best_crop_uri_raises_key_error() -> None:
    frames = [_frame(0, 0.0, [_person("cam01-t1")])]

    with pytest.raises(KeyError):
        build_twin(
            segment_id="s",
            camera_id="cam01",
            site_id="site1",
            start_ts=T0,
            end_ts=T0 + timedelta(seconds=10),
            sample_fps=2.0,
            frame_size=(100, 100),
            frames=frames,
            best_crop_uris={},  # missing cam01-t1
            embedding_indices={"cam01-t1": 0},
        )
