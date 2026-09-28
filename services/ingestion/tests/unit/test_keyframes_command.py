"""Tests for ingestion.adapters.keyframes.build_keyframe_extract_command — pure argv."""

from pathlib import Path

from ingestion.adapters.keyframes import build_keyframe_extract_command


def test_build_keyframe_extract_command_default_1fps() -> None:
    cmd = build_keyframe_extract_command(Path("/work/seg.ts"), Path("/work/kf"))

    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == str(Path("/work/seg.ts"))
    assert cmd[cmd.index("-vf") + 1] == "fps=1.0"
    assert cmd[-1] == str(Path("/work/kf/%04d.jpg"))


def test_build_keyframe_extract_command_custom_fps() -> None:
    cmd = build_keyframe_extract_command(Path("/work/seg.ts"), Path("/work/kf"), fps=2.0)

    assert cmd[cmd.index("-vf") + 1] == "fps=2.0"
