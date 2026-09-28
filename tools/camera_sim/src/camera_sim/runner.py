"""Launches and supervises one ffmpeg process per camera in the manifest,
publishing each as a real-time RTSP stream to MediaMTX
(design_architecture.md §7.1: `ffmpeg -re -stream_loop -1 -> MediaMTX`).

Start synchronization: all cameras are launched in one tight loop (Popen is
~ms-scale), each seeking into its own file at its own `start_offset_s`
before real-time playback begins — this is what keeps multi-view datasets
(WILDTRACK/MEVA) time-aligned. It is not sub-frame-accurate, and looped
playback can drift across very long runs; that is an accepted limitation
of a dev/demo simulator, not a claim of broadcast-grade sync.
"""

from __future__ import annotations

import asyncio
import shlex

from vms_common.logging import get_logger

from camera_sim.manifest import CameraSource

log = get_logger(__name__)

RESTART_BACKOFF_SECONDS = 5.0


def build_ffmpeg_command(
    source: CameraSource, *, mediamtx_url: str, reencode: bool = False
) -> list[str]:
    """Build the ffmpeg argv for one camera.

    `-c copy` (default) remuxes without re-encoding — cheap, but requires
    the source file to already be H.264. Pass `reencode=True` for sources
    in other codecs (some MEVA/UCF-Crime clips aren't H.264).
    """
    codec_args = (
        ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"] if reencode else ["-c", "copy"]
    )
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "warning",
        "-re",
        "-stream_loop",
        "-1",
        "-ss",
        str(source.start_offset_s),
        "-i",
        source.file,
        *codec_args,
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        f"{mediamtx_url.rstrip('/')}/{source.id}",
    ]


async def _supervise(source: CameraSource, *, mediamtx_url: str, reencode: bool) -> None:
    """Run ffmpeg for one camera forever, restarting on unexpected exit."""
    cmd = build_ffmpeg_command(source, mediamtx_url=mediamtx_url, reencode=reencode)
    log.info(
        "camera_sim_starting",
        camera_id=source.id,
        file=source.file,
        start_offset_s=source.start_offset_s,
        command=shlex.join(cmd),
    )

    while True:
        process = await asyncio.create_subprocess_exec(*cmd)
        returncode = await process.wait()
        log.warning("camera_sim_ffmpeg_exited", camera_id=source.id, returncode=returncode)
        await asyncio.sleep(RESTART_BACKOFF_SECONDS)


async def run_all(
    sources: list[CameraSource], *, mediamtx_url: str, reencode: bool = False
) -> None:
    """Start every camera and supervise them until cancelled (Ctrl+C)."""
    tasks = [
        asyncio.create_task(_supervise(source, mediamtx_url=mediamtx_url, reencode=reencode))
        for source in sources
    ]
    await asyncio.gather(*tasks)
