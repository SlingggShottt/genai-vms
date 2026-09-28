"""Probes a camera's RTSP stream once (fps/width/height/codec) so `segment.v1`
carries real values without re-probing on every segment. Falls back to
configured defaults — logged, never fatal — since a flaky probe shouldn't
block ingestion (FR-ING shall keep recording regardless).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from vms_common.logging import get_logger

log = get_logger(__name__)

PROBE_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class StreamInfo:
    fps: float
    width: int
    height: int
    codec: str


async def probe_stream(
    rtsp_url: str,
    *,
    default_fps: float = 25.0,
    default_width: int = 1920,
    default_height: int = 1080,
    default_codec: str = "h264",
) -> StreamInfo:
    """ffprobe the RTSP source for its video stream's fps/width/height/codec."""
    defaults = StreamInfo(
        fps=default_fps, width=default_width, height=default_height, codec=default_codec
    )
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,codec_name",
        "-of",
        "json",
        rtsp_url,
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=PROBE_TIMEOUT_SECONDS)
        data = json.loads(stdout)
        stream = data["streams"][0]
        num, _, den = stream["r_frame_rate"].partition("/")
        fps = float(num) / float(den) if den and float(den) != 0 else defaults.fps
        return StreamInfo(
            fps=fps,
            width=int(stream["width"]),
            height=int(stream["height"]),
            codec=stream["codec_name"],
        )
    except (
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        ValueError,
    ) as exc:
        log.warning("stream_probe_failed_using_defaults", rtsp_url=rtsp_url, error=str(exc))
        return defaults
