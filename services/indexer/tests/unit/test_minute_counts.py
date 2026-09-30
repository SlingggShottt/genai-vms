from __future__ import annotations

from datetime import UTC, datetime

from indexer.domain.minute_counts import MinuteCountKey, compute_minute_counts, minute_bucket
from vms_common.contracts.twin import Frame, FrameObject, FrameSize, TwinV1


def _obj(track_id: str, category: str) -> FrameObject:
    return FrameObject(track_id=track_id, category=category, conf=0.9, bbox=(0.1, 0.1, 0.2, 0.2))


def _twin(frames: list[Frame]) -> TwinV1:
    return TwinV1(
        segment_id="cam01_20261005T101500Z_000001",
        camera_id="cam01",
        site_id="rvce-campus",
        start_ts=datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC),
        end_ts=datetime(2026, 10, 5, 10, 15, 10, tzinfo=UTC),
        sample_fps=2.0,
        frame_size=FrameSize(w=1920, h=1080),
        frames=frames,
    )


def test_minute_bucket_truncates_seconds_and_microseconds() -> None:
    ts = datetime(2026, 10, 5, 10, 15, 42, 123456, tzinfo=UTC)
    assert minute_bucket(ts) == datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)


def test_takes_the_max_simultaneous_count_per_category_within_a_minute() -> None:
    minute = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)
    twin = _twin(
        [
            Frame(
                ts=minute.replace(second=1),
                idx=0,
                keyframe_uri="s3://vms-keyframes/f0.jpg",
                objects=[_obj("cam01-t1", "person")],
            ),
            Frame(
                ts=minute.replace(second=5),
                idx=1,
                keyframe_uri="s3://vms-keyframes/f1.jpg",
                objects=[_obj("cam01-t1", "person"), _obj("cam01-t2", "person")],
            ),
        ]
    )

    counts = compute_minute_counts(twin)

    assert counts == {MinuteCountKey(minute, "person"): 2}


def test_splits_contributions_across_a_minute_boundary() -> None:
    minute_a = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)
    minute_b = datetime(2026, 10, 5, 10, 16, 0, tzinfo=UTC)
    twin = _twin(
        [
            Frame(
                ts=minute_a.replace(second=59),
                idx=0,
                keyframe_uri="s3://vms-keyframes/f0.jpg",
                objects=[_obj("cam01-t1", "car")],
            ),
            Frame(
                ts=minute_b.replace(second=1),
                idx=1,
                keyframe_uri="s3://vms-keyframes/f1.jpg",
                objects=[_obj("cam01-t1", "car"), _obj("cam01-t2", "car")],
            ),
        ]
    )

    counts = compute_minute_counts(twin)

    assert counts == {
        MinuteCountKey(minute_a, "car"): 1,
        MinuteCountKey(minute_b, "car"): 2,
    }


def test_empty_frames_contribute_nothing() -> None:
    assert compute_minute_counts(_twin([])) == {}
