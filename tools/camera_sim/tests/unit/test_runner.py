"""Tests for camera_sim.runner.build_ffmpeg_command — pure argv construction."""

from pathlib import Path

from camera_sim.manifest import CameraSource
from camera_sim.runner import build_ffmpeg_command


def _source(tmp_path: Path, camera_id: str, **kwargs: object) -> CameraSource:
    video = tmp_path / f"{camera_id}.mp4"
    video.write_bytes(b"not a real video, just needs to exist")
    return CameraSource(id=camera_id, file=str(video), **kwargs)


def test_build_ffmpeg_command_stream_copies_by_default(tmp_path: Path) -> None:
    source = _source(tmp_path, "cam01", start_offset_s=5.0)

    cmd = build_ffmpeg_command(source, mediamtx_url="rtsp://mediamtx:8554")

    assert cmd[0] == "ffmpeg"
    assert "-re" in cmd
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    assert cmd[cmd.index("-ss") + 1] == "5.0"
    assert cmd[cmd.index("-i") + 1] == source.file
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "rtsp://mediamtx:8554/cam01"


def test_build_ffmpeg_command_reencode_uses_libx264(tmp_path: Path) -> None:
    source = _source(tmp_path, "cam02")

    cmd = build_ffmpeg_command(source, mediamtx_url="rtsp://mediamtx:8554", reencode=True)

    assert "-c" not in cmd  # stream-copy flag must not also be present
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[-1] == "rtsp://mediamtx:8554/cam02"


def test_build_ffmpeg_command_strips_trailing_slash_from_base_url(tmp_path: Path) -> None:
    source = _source(tmp_path, "cam03")

    cmd = build_ffmpeg_command(source, mediamtx_url="rtsp://mediamtx:8554/")

    assert cmd[-1] == "rtsp://mediamtx:8554/cam03"
