"""P2-J3: pure timeline/playlist/density/frame-filtering logic — no DB, no S3."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api.domain.recordings import (
    Gap,
    MinuteCountRow,
    SegmentWindow,
    bucket_density,
    build_playlist_m3u8,
    build_timeline,
    frames_in_range,
)
from vms_common.contracts.twin import Frame, FrameObject, FrameSize, TwinV1

T0 = datetime(2026, 10, 5, 10, 0, 0, tzinfo=UTC)


def _seg(offset_s: int, duration_s: int = 10, segment_id: str | None = None) -> SegmentWindow:
    start = T0 + timedelta(seconds=offset_s)
    return SegmentWindow(
        segment_id=segment_id or f"seg-{offset_s}",
        start_ts=start,
        end_ts=start + timedelta(seconds=duration_s),
        uri=f"https://presigned/{offset_s}",
    )


# --- build_timeline -----------------------------------------------------


def test_contiguous_segments_produce_no_gaps() -> None:
    segments = [_seg(0), _seg(10), _seg(20)]
    timeline = build_timeline(segments, range_start=T0, range_end=T0 + timedelta(seconds=30))
    assert timeline == segments


def test_leading_gap_before_the_first_segment() -> None:
    segments = [_seg(10)]
    range_start = T0
    range_end = T0 + timedelta(seconds=20)
    timeline = build_timeline(segments, range_start=range_start, range_end=range_end)
    assert timeline == [Gap(range_start, segments[0].start_ts), segments[0]]


def test_trailing_gap_after_the_last_segment() -> None:
    segments = [_seg(0)]
    range_end = T0 + timedelta(seconds=30)
    timeline = build_timeline(segments, range_start=T0, range_end=range_end)
    assert timeline == [segments[0], Gap(segments[0].end_ts, range_end)]


def test_interior_gap_between_two_segments() -> None:
    seg_a = _seg(0)
    seg_b = _seg(30)
    timeline = build_timeline([seg_a, seg_b], range_start=T0, range_end=T0 + timedelta(seconds=40))
    assert timeline == [seg_a, Gap(seg_a.end_ts, seg_b.start_ts), seg_b]


def test_no_segments_at_all_is_one_whole_gap() -> None:
    range_end = T0 + timedelta(seconds=20)
    timeline = build_timeline([], range_start=T0, range_end=range_end)
    assert timeline == [Gap(T0, range_end)]


def test_segment_extending_past_range_end_leaves_no_trailing_gap() -> None:
    seg = _seg(0, duration_s=60)
    range_end = T0 + timedelta(seconds=30)
    timeline = build_timeline([seg], range_start=T0, range_end=range_end)
    assert timeline == [seg]


# --- build_playlist_m3u8 -------------------------------------------------


def test_playlist_has_program_date_time_and_extinf_per_segment() -> None:
    segments = [_seg(0), _seg(10)]
    timeline = build_timeline(segments, range_start=T0, range_end=T0 + timedelta(seconds=20))
    playlist = build_playlist_m3u8(timeline)

    assert playlist.startswith("#EXTM3U\n")
    assert playlist.count("#EXT-X-PROGRAM-DATE-TIME:") == 2
    assert playlist.count("#EXTINF:10.000,") == 2
    assert "https://presigned/0" in playlist
    assert "https://presigned/10" in playlist
    assert playlist.strip().endswith("#EXT-X-ENDLIST")


def test_playlist_marks_an_interior_gap_with_discontinuity() -> None:
    seg_a = _seg(0)
    seg_b = _seg(30)
    timeline = build_timeline([seg_a, seg_b], range_start=T0, range_end=T0 + timedelta(seconds=40))
    playlist = build_playlist_m3u8(timeline)

    assert playlist.count("#EXT-X-DISCONTINUITY") == 1
    # comes between the two segment URIs
    assert playlist.index("presigned/0") < playlist.index("#EXT-X-DISCONTINUITY")
    assert playlist.index("#EXT-X-DISCONTINUITY") < playlist.index("presigned/30")


def test_playlist_marks_every_segment_boundary_with_discontinuity() -> None:
    # Ingestion's segmenter runs ffmpeg with `-reset_timestamps 1`, so even
    # back-to-back segments each start their own timestamp clock. Without a
    # marker hls.js treats them as one continuous timeline and a seek past the
    # buffered range ends the player early (duration collapses to the buffer).
    segments = [_seg(0), _seg(10), _seg(20)]
    timeline = build_timeline(segments, range_start=T0, range_end=T0 + timedelta(seconds=30))
    lines = build_playlist_m3u8(timeline).splitlines()

    assert lines.count("#EXT-X-DISCONTINUITY") == 2
    # none before the first segment…
    assert "#EXT-X-DISCONTINUITY" not in lines[: lines.index("https://presigned/0")]
    # …and one directly ahead of each later segment's PROGRAM-DATE-TIME/EXTINF/URI.
    for uri in ("https://presigned/10", "https://presigned/20"):
        assert lines[lines.index(uri) - 3] == "#EXT-X-DISCONTINUITY"


def test_playlist_gap_and_segment_boundary_yield_a_single_marker() -> None:
    timeline = build_timeline(
        [_seg(0), _seg(30)], range_start=T0, range_end=T0 + timedelta(seconds=40)
    )
    assert build_playlist_m3u8(timeline).count("#EXT-X-DISCONTINUITY") == 1


def test_playlist_does_not_mark_leading_or_trailing_gaps() -> None:
    segments = [_seg(10)]
    timeline = build_timeline(segments, range_start=T0, range_end=T0 + timedelta(seconds=40))
    playlist = build_playlist_m3u8(timeline)
    assert "#EXT-X-DISCONTINUITY" not in playlist


def test_playlist_with_no_segments_still_has_a_valid_header_and_endlist() -> None:
    timeline = build_timeline([], range_start=T0, range_end=T0 + timedelta(seconds=10))
    playlist = build_playlist_m3u8(timeline)
    assert playlist.startswith("#EXTM3U\n")
    assert playlist.strip().endswith("#EXT-X-ENDLIST")
    assert "#EXT-X-DISCONTINUITY" not in playlist


# --- bucket_density -------------------------------------------------------


def test_bucket_density_sums_minutes_into_the_right_bucket() -> None:
    rows = [
        MinuteCountRow(T0, 2),
        MinuteCountRow(T0 + timedelta(minutes=1), 3),
        MinuteCountRow(T0 + timedelta(minutes=2), 1),
    ]
    buckets = bucket_density(
        rows, range_start=T0, range_end=T0 + timedelta(minutes=3), bucket_seconds=120
    )
    assert [b.count for b in buckets] == [5, 1]


def test_bucket_density_zero_fills_empty_buckets() -> None:
    buckets = bucket_density(
        [], range_start=T0, range_end=T0 + timedelta(minutes=3), bucket_seconds=60
    )
    assert [b.count for b in buckets] == [0, 0, 0]


def test_bucket_density_covers_a_partial_final_bucket() -> None:
    buckets = bucket_density(
        [MinuteCountRow(T0, 4)],
        range_start=T0,
        range_end=T0 + timedelta(seconds=90),
        bucket_seconds=60,
    )
    assert len(buckets) == 2
    assert buckets[-1].end_ts == T0 + timedelta(seconds=90)


# --- frames_in_range -------------------------------------------------------


def _twin_with_frames(*offsets_s: int) -> TwinV1:
    frames = [
        Frame(
            ts=T0 + timedelta(seconds=s),
            idx=i,
            keyframe_uri=f"s3://vms-keyframes/{i}.jpg",
            objects=[
                FrameObject(track_id="t1", category="person", conf=0.9, bbox=(0.1, 0.1, 0.2, 0.2))
            ],
        )
        for i, s in enumerate(offsets_s)
    ]
    return TwinV1(
        segment_id="seg1",
        camera_id="cam01",
        site_id="rvce-campus",
        start_ts=T0,
        end_ts=T0 + timedelta(seconds=10),
        sample_fps=2.0,
        frame_size=FrameSize(w=1920, h=1080),
        frames=frames,
    )


def test_frames_in_range_is_inclusive_of_both_ends() -> None:
    twin = _twin_with_frames(0, 5, 10)
    result = frames_in_range(twin, start=T0, end=T0 + timedelta(seconds=10))
    assert [f.idx for f in result] == [0, 1, 2]


def test_frames_in_range_excludes_frames_outside_the_window() -> None:
    twin = _twin_with_frames(0, 5, 10)
    result = frames_in_range(twin, start=T0 + timedelta(seconds=1), end=T0 + timedelta(seconds=9))
    assert [f.idx for f in result] == [1]
