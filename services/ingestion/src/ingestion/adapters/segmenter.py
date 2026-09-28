"""Runs ffmpeg's segment muxer against one camera's RTSP stream and detects
each completed segment via the segment list file ffmpeg appends to
(design_architecture.md §7.1: `ffmpeg -c copy` segmenter; FR-ING-02).

Wall-clock timing model: the moment a new line appears in the segment list
is treated as that segment's end and the next segment's start — ffmpeg
opens file N+1 the instant it closes file N, so this stays contiguous
without needing to trust ffmpeg's internal (PTS-based) clock for
wall-clock purposes.

Verified locally (no camera needed — `ffmpeg -f lavfi -i testsrc=...` piped
through this exact muxer invocation): `-segment_list_type flat` writes one
plain filename per completed segment, one per line, as each one closes.
Also confirmed: with `-c copy`, a segment can only be cut on a keyframe, so
actual segment length is `>= segment_seconds`, rounded up to the source's
next keyframe — on a source with a 10s keyframe interval, asking for 5s
segments produced two 10s segments, not four 5s ones. Real cameras
typically keyframe every 1-2s so this rarely matters, but it's why the
wall-clock timing model above observes actual completion rather than
assuming exactly `segment_seconds`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SEGMENT_LIST_POLL_SECONDS = 0.5


@dataclass(frozen=True)
class CompletedSegment:
    """One finished local `.ts` file, with the wall-clock window Python observed."""

    local_path: Path
    seq: int
    start_ts: datetime
    end_ts: datetime


def build_ffmpeg_segment_command(
    *,
    rtsp_url: str,
    out_dir: Path,
    camera_id: str,
    segment_list_path: Path,
    segment_seconds: int,
) -> list[str]:
    """ffmpeg argv: stream-copy segmenter (FR-ING-02: no re-encode where possible).

    Segments can only be cut on keyframes when stream-copying — see module
    docstring for what that means for actual segment length.
    """
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        "tcp",
        "-i",
        rtsp_url,
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-reset_timestamps",
        "1",
        "-segment_list",
        str(segment_list_path),
        "-segment_list_type",
        "flat",
        "-segment_list_flags",
        "+live",
        str(out_dir / f"{camera_id}_%06d.ts"),
    ]


async def watch_segments(
    *, segment_list_path: Path, out_dir: Path, worker_start: datetime
) -> AsyncIterator[CompletedSegment]:
    """Yield each segment as ffmpeg finishes writing it (polls the segment list).

    Runs until the caller cancels it — the ffmpeg process's own lifetime is
    what actually bounds this (see adapters usage in `ingestion.worker`).
    """
    seen = 0
    previous_end = worker_start
    seq = 0

    while True:
        exists = await asyncio.to_thread(segment_list_path.exists)
        if exists:
            text = await asyncio.to_thread(segment_list_path.read_text)
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            for filename in lines[seen:]:
                now = datetime.now(UTC)
                yield CompletedSegment(
                    local_path=out_dir / filename, seq=seq, start_ts=previous_end, end_ts=now
                )
                previous_end = now
                seq += 1
            seen = len(lines)
        await asyncio.sleep(SEGMENT_LIST_POLL_SECONDS)
