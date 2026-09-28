"""Decodes a downloaded segment file and samples frames at a target fps
using PyAV (design_architecture.md §7.1: "Decode with PyAV, sample at
sample_fps"). Sampling is done by wall-clock spacing (keep a frame once
`1/fps` seconds have passed since the last kept one), not by frame index,
so it's correct regardless of the segment's actual encoded frame rate.

`pts_seconds` is reported **relative to the first decoded frame**, not the
container's raw PTS. Verified against a real MPEG-TS file (the format
ingestion actually produces): the first decoded frame's raw PTS was
1.48s, not 0 — MPEG-TS muxing adds an arbitrary starting offset. Without
normalizing to the first frame, every `Frame.ts` built from this would be
offset by that same arbitrary amount, unrelated to wall-clock time.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np


@dataclass(frozen=True)
class SampledFrame:
    idx: int
    pts_seconds: float
    rgb: np.ndarray  # (H, W, 3), uint8


def sample_frames(segment_path: Path, *, fps: float) -> Iterator[SampledFrame]:
    """Decode `segment_path` and yield frames spaced >= `1/fps` seconds apart."""
    if fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")
    min_interval_s = 1.0 / fps

    with av.open(str(segment_path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"

        idx = 0
        base_pts_s: float | None = None
        next_keep_at = 0.0
        for frame in container.decode(stream):
            raw_pts_s = float(frame.pts * stream.time_base) if frame.pts is not None else 0.0
            if base_pts_s is None:
                base_pts_s = raw_pts_s
            pts_seconds = raw_pts_s - base_pts_s

            if pts_seconds + 1e-6 < next_keep_at:
                continue
            rgb = frame.to_ndarray(format="rgb24")
            yield SampledFrame(idx=idx, pts_seconds=pts_seconds, rgb=rgb)
            idx += 1
            next_keep_at = pts_seconds + min_interval_s


def probe_video(segment_path: Path) -> tuple[int, int, float]:
    """Return `(width, height, fps)` of `segment_path`'s video stream."""
    with av.open(str(segment_path)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate) if stream.average_rate is not None else 0.0
        return stream.codec_context.width, stream.codec_context.height, fps
