"""Pure recordings/playlist/density logic — no I/O (P2-J3, FR-PLAY-01).

`build_timeline` is the one gap-detection pass shared by both the JSON
`/segments` response and the `.m3u8` playlist, so "gaps return explicit
markers instead of silent skips" (P2-J3 AC) is implemented once, not twice.
Segment timestamps are used as-is, never clipped to the request window —
design_architecture.md §6.3/§9 rules out transcoding, so a presigned
segment URI always serves its *whole* `.ts` file regardless of how much of
the requested `[start, end)` it actually covers.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import NamedTuple

from vms_common.contracts.twin import Frame, TwinV1


class SegmentWindow(NamedTuple):
    segment_id: str
    start_ts: datetime
    end_ts: datetime
    uri: str  # presigned GET url — callers presign before building a timeline


class Gap(NamedTuple):
    start_ts: datetime
    end_ts: datetime


TimelineItem = SegmentWindow | Gap


def build_timeline(
    segments: Sequence[SegmentWindow], *, range_start: datetime, range_end: datetime
) -> list[TimelineItem]:
    """`segments` must be sorted by `start_ts` and (in the normal case)
    non-overlapping, matching how ingestion's segmenter writes `media.segments`.
    An overlapping segment is still included (never dropped), just won't
    open a gap by itself.
    """
    timeline: list[TimelineItem] = []
    cursor = range_start
    for seg in segments:
        if seg.start_ts > cursor:
            timeline.append(Gap(cursor, seg.start_ts))
        timeline.append(seg)
        cursor = max(cursor, seg.end_ts)
    if cursor < range_end:
        timeline.append(Gap(cursor, range_end))
    return timeline


def build_playlist_m3u8(timeline: Sequence[TimelineItem]) -> str:
    """HLS VOD playlist. `#EXT-X-DISCONTINUITY` precedes every segment after
    the first: ingestion's segmenter runs ffmpeg with `-reset_timestamps 1`,
    so each stored `.ts` starts its own timestamp clock, and a recording gap
    is a discontinuity too. Without the marker hls.js assumes one continuous
    timeline and, on a seek past the buffered range, places the fetched
    segment at the wrong time — the player ends early and `duration` collapses
    to the buffered length. A leading or trailing gap has no adjacent segment
    to be discontinuous from, so it gets no marker; it just isn't part of the
    playlist. `#EXT-X-PROGRAM-DATE-TIME` precedes every segment (not just the
    first) so the UI can map player time to wall clock across a playlist that
    may itself contain gaps.
    """
    segment_durations = [
        (item.end_ts - item.start_ts).total_seconds()
        for item in timeline
        if isinstance(item, SegmentWindow)
    ]
    target_duration = math.ceil(max(segment_durations, default=1.0))

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        f"#EXT-X-TARGETDURATION:{target_duration}",
    ]
    # Gaps carry no playlist entry of their own: the discontinuity marker
    # goes before the segment that follows, so a gap between two segments and
    # a plain segment boundary both come out as exactly one marker.
    seen_a_segment = False
    for item in timeline:
        if isinstance(item, Gap):
            continue
        if seen_a_segment:
            lines.append("#EXT-X-DISCONTINUITY")
        duration = (item.end_ts - item.start_ts).total_seconds()
        lines.append(f"#EXT-X-PROGRAM-DATE-TIME:{item.start_ts.isoformat()}")
        lines.append(f"#EXTINF:{duration:.3f},")
        lines.append(item.uri)
        seen_a_segment = True
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


class MinuteCountRow(NamedTuple):
    minute_ts: datetime
    count: int


class DensityBucket(NamedTuple):
    start_ts: datetime
    end_ts: datetime
    count: int


def bucket_density(
    rows: Sequence[MinuteCountRow],
    *,
    range_start: datetime,
    range_end: datetime,
    bucket_seconds: int,
) -> list[DensityBucket]:
    """Every bucket in `[range_start, range_end)` is returned, zero-filled
    where there's no data — unlike `vision.minute_counts` itself (absence,
    not zero; see indexer's README), a density *sparkline* needs a
    continuous series to plot, so the gap-vs-zero distinction is collapsed
    here on purpose.
    """
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")

    sums: dict[int, int] = defaultdict(int)
    for row in rows:
        idx = int((row.minute_ts - range_start).total_seconds() // bucket_seconds)
        sums[idx] += row.count

    span_seconds = (range_end - range_start).total_seconds()
    n_buckets = max(1, math.ceil(span_seconds / bucket_seconds))
    buckets: list[DensityBucket] = []
    for idx in range(n_buckets):
        start = range_start + timedelta(seconds=idx * bucket_seconds)
        end = min(start + timedelta(seconds=bucket_seconds), range_end)
        buckets.append(DensityBucket(start, end, sums.get(idx, 0)))
    return buckets


def frames_in_range(twin: TwinV1, *, start: datetime, end: datetime) -> list[Frame]:
    """`twin.frames` within `[start, end]`, inclusive both ends — callers
    already picked segments overlapping the window, so this just trims to
    the exact requested bound.
    """
    return [f for f in twin.frames if start <= f.ts <= end]
