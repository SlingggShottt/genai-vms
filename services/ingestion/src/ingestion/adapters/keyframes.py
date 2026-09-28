"""Extracts keyframe thumbnails from a completed segment (FR-ING-04: at
least one per second of video). Verified locally: `-vf fps=1` against a
10s test segment produced exactly 10 JPEGs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


def build_keyframe_extract_command(
    segment_path: Path, out_dir: Path, *, fps: float = 1.0
) -> list[str]:
    """ffmpeg argv: one JPEG per `1/fps` seconds of `segment_path`, into `out_dir`."""
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "warning",
        "-i",
        str(segment_path),
        "-vf",
        f"fps={fps}",
        "-q:v",
        "3",
        str(out_dir / "%04d.jpg"),
    ]


async def extract_keyframes(segment_path: Path, out_dir: Path, *, fps: float = 1.0) -> list[Path]:
    """Run ffmpeg to extract keyframes; return the resulting file paths in order."""
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    cmd = build_keyframe_extract_command(segment_path, out_dir, fps=fps)
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    returncode = await process.wait()
    if returncode != 0:
        raise RuntimeError(f"keyframe extraction failed for {segment_path} (exit {returncode})")
    return await asyncio.to_thread(lambda: sorted(out_dir.glob("*.jpg")))
