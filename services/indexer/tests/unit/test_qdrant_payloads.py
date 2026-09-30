from __future__ import annotations

from datetime import UTC, datetime

from indexer.domain.qdrant_payloads import build_frame_payload, build_track_payload
from vms_common.contracts.twin import Frame, FrameObject, ObjectAttributes, TrackSummary


def _frame_obj(category: str) -> FrameObject:
    return FrameObject(track_id="cam01-t1", category=category, conf=0.9, bbox=(0.1, 0.1, 0.2, 0.2))


def test_build_frame_payload_counts_categories_and_persons() -> None:
    frame = Frame(
        ts=datetime(2026, 10, 5, 10, 15, 0, 500000, tzinfo=UTC),
        idx=3,
        keyframe_uri="s3://vms-keyframes/f.jpg",
        objects=[_frame_obj("person"), _frame_obj("person"), _frame_obj("car")],
    )

    payload = build_frame_payload(
        frame, camera_id="cam01", site_id="rvce-campus", segment_id="seg1"
    )

    assert payload["camera_id"] == "cam01"
    assert payload["site_id"] == "rvce-campus"
    assert payload["segment_id"] == "seg1"
    assert payload["keyframe_uri"] == "s3://vms-keyframes/f.jpg"
    assert payload["categories"] == ["car", "person"]
    assert payload["person_count"] == 2
    assert payload["ts"] == int(frame.ts.timestamp() * 1000)


def test_build_frame_payload_handles_no_objects() -> None:
    frame = Frame(
        ts=datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC),
        idx=0,
        keyframe_uri="s3://vms-keyframes/f.jpg",
        objects=[],
    )

    payload = build_frame_payload(
        frame, camera_id="cam01", site_id="rvce-campus", segment_id="seg1"
    )

    assert payload["categories"] == []
    assert payload["person_count"] == 0


def test_build_track_payload_dedupes_colors_and_drops_none() -> None:
    track = TrackSummary(
        track_id="cam03-t412",
        category="person",
        first_ts=datetime(2026, 10, 5, 10, 15, 0, 500000, tzinfo=UTC),
        last_ts=datetime(2026, 10, 5, 10, 15, 9, 500000, tzinfo=UTC),
        dwell_s=9.5,
        zones_visited=["entrance"],
        attributes_summary=ObjectAttributes(upper_color="red", lower_color="red"),
        best_crop_uri="s3://vms-crops/cam03-t412.jpg",
        embedding_index=0,
    )

    payload = build_track_payload(track, camera_id="cam03", segment_id="seg1")

    assert payload["track_id"] == "cam03-t412"
    assert payload["camera_id"] == "cam03"
    assert payload["category"] == "person"
    assert payload["colors"] == ["red"]
    assert payload["zones"] == ["entrance"]
    assert payload["crop_uri"] == "s3://vms-crops/cam03-t412.jpg"
    assert payload["segment_ids"] == ["seg1"]
    assert payload["first_ts"] == int(track.first_ts.timestamp() * 1000)
    assert payload["last_ts"] == int(track.last_ts.timestamp() * 1000)


def test_build_track_payload_with_no_colors() -> None:
    track = TrackSummary(
        track_id="cam03-t1",
        category="bicycle",
        first_ts=datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC),
        last_ts=datetime(2026, 10, 5, 10, 15, 5, tzinfo=UTC),
        dwell_s=5.0,
        best_crop_uri="s3://vms-crops/cam03-t1.jpg",
        embedding_index=0,
    )

    payload = build_track_payload(track, camera_id="cam03", segment_id="seg1")

    assert payload["colors"] == []
