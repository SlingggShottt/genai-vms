"""Tests for perception.adapters.decoder — generates a tiny synthetic clip
with ffmpeg at test time (this project already requires ffmpeg for
ingestion; skipped if it's not on PATH).

Verified against a real MPEG-TS file: the container's raw PTS does not
start at 0 (an arbitrary muxer offset) — these tests exist specifically to
catch a regression of that (see decoder.py's docstring for what broke
without the fix).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from perception.adapters.decoder import sample_frames

FFMPEG_PATH = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG_PATH is None, reason="ffmpeg not on PATH")


@pytest.fixture
def synthetic_clip(tmp_path: Path) -> Path:
    """A short H.264-in-MPEG-TS test clip, same container ingestion produces."""
    out = tmp_path / "clip.ts"
    subprocess.run(
        [
            FFMPEG_PATH,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=6:size=320x240:rate=25",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(out),
        ],
        check=True,
        timeout=60,
    )
    return out


def test_sample_frames_first_frame_starts_at_zero(synthetic_clip: Path) -> None:
    frames = list(sample_frames(synthetic_clip, fps=2.0))
    assert frames[0].pts_seconds == pytest.approx(0.0, abs=0.05)


def test_sample_frames_count_matches_fps_and_duration(synthetic_clip: Path) -> None:
    frames = list(sample_frames(synthetic_clip, fps=2.0))
    # 6s at 2fps -> ~12 frames; allow slack for frame-boundary rounding
    assert 10 <= len(frames) <= 13


def test_sample_frames_spacing_is_at_least_the_requested_interval(
    synthetic_clip: Path,
) -> None:
    frames = list(sample_frames(synthetic_clip, fps=2.0))
    for prev, curr in zip(frames, frames[1:], strict=False):
        assert curr.pts_seconds - prev.pts_seconds >= 0.5 - 0.05


def test_sample_frames_shape_matches_source_resolution(synthetic_clip: Path) -> None:
    frames = list(sample_frames(synthetic_clip, fps=1.0))
    assert frames[0].rgb.shape == (240, 320, 3)


def test_sample_frames_rejects_non_positive_fps(synthetic_clip: Path) -> None:
    with pytest.raises(ValueError, match="fps must be > 0"):
        list(sample_frames(synthetic_clip, fps=0))
