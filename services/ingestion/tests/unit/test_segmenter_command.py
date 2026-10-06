"""Tests for ingestion.adapters.segmenter.build_ffmpeg_segment_command — pure argv."""

from pathlib import Path

from ingestion.adapters.segmenter import build_ffmpeg_segment_command


def test_build_ffmpeg_segment_command_shape() -> None:
    cmd = build_ffmpeg_segment_command(
        rtsp_url="rtsp://mediamtx:8554/cam01",
        out_dir=Path("/work/cam01"),
        camera_id="cam01",
        segment_list_path=Path("/work/cam01/segments.list"),
        segment_seconds=10,
    )

    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "rtsp://mediamtx:8554/cam01"
    assert cmd[cmd.index("-c") + 1] == "copy"  # FR-ING-02: no re-encode
    assert cmd[cmd.index("-segment_time") + 1] == "10"
    assert cmd[cmd.index("-segment_list") + 1] == str(Path("/work/cam01/segments.list"))
    assert cmd[cmd.index("-segment_list_type") + 1] == "flat"
    assert cmd[-1] == str(Path("/work/cam01/cam01_%06d.ts"))


def test_the_input_has_a_socket_timeout_so_a_dead_publisher_cannot_hang_ffmpeg() -> None:
    cmd = build_ffmpeg_segment_command(
        rtsp_url="rtsp://mediamtx:8554/cam01",
        out_dir=Path("/work/cam01"),
        camera_id="cam01",
        segment_list_path=Path("/work/cam01/segments.list"),
        segment_seconds=10,
        io_timeout_seconds=15,
    )
    assert cmd[cmd.index("-timeout") + 1] == "15000000"
    assert cmd.index("-timeout") < cmd.index("-i")  # an input option: it must precede -i
