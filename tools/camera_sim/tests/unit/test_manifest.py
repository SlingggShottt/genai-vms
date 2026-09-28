"""Tests for camera_sim.manifest — pure validation, no ffmpeg/network."""

from pathlib import Path

import pytest
from camera_sim.manifest import load_manifest
from pydantic import ValidationError


def _touch(path: Path) -> str:
    path.write_bytes(b"not a real video, just needs to exist")
    return str(path)


def test_load_manifest_parses_valid_yaml(tmp_path: Path) -> None:
    video = _touch(tmp_path / "cam01.mp4")
    manifest_path = tmp_path / "camera_sim.yaml"
    manifest_path.write_text(f"""
mediamtx_url: rtsp://mediamtx:8554
cameras:
  - id: cam01
    file: {video}
    start_offset_s: 2.5
""")

    manifest = load_manifest(manifest_path)

    assert manifest.mediamtx_url == "rtsp://mediamtx:8554"
    assert len(manifest.cameras) == 1
    assert manifest.cameras[0].id == "cam01"
    assert manifest.cameras[0].start_offset_s == 2.5


def test_load_manifest_defaults_offset_and_mediamtx_url(tmp_path: Path) -> None:
    video = _touch(tmp_path / "cam01.mp4")
    manifest_path = tmp_path / "camera_sim.yaml"
    manifest_path.write_text(f"cameras:\n  - id: cam01\n    file: {video}\n")

    manifest = load_manifest(manifest_path)

    assert manifest.mediamtx_url == "rtsp://localhost:8554"
    assert manifest.cameras[0].start_offset_s == 0.0


def test_load_manifest_rejects_missing_video_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / "camera_sim.yaml"
    manifest_path.write_text(f"cameras:\n  - id: cam01\n    file: {tmp_path / 'missing.mp4'}\n")

    with pytest.raises(ValidationError, match="video file not found"):
        load_manifest(manifest_path)


def test_load_manifest_rejects_duplicate_camera_ids(tmp_path: Path) -> None:
    video1 = _touch(tmp_path / "cam01.mp4")
    video2 = _touch(tmp_path / "cam01b.mp4")
    manifest_path = tmp_path / "camera_sim.yaml"
    manifest_path.write_text(
        f"cameras:\n  - id: cam01\n    file: {video1}\n  - id: cam01\n    file: {video2}\n"
    )

    with pytest.raises(ValidationError, match="duplicate camera ids"):
        load_manifest(manifest_path)


def test_load_manifest_rejects_empty_camera_list(tmp_path: Path) -> None:
    manifest_path = tmp_path / "camera_sim.yaml"
    manifest_path.write_text("cameras: []\n")

    with pytest.raises(ValidationError, match="at least one camera"):
        load_manifest(manifest_path)


def test_load_manifest_rejects_negative_offset(tmp_path: Path) -> None:
    video = _touch(tmp_path / "cam01.mp4")
    manifest_path = tmp_path / "camera_sim.yaml"
    manifest_path.write_text(
        f"cameras:\n  - id: cam01\n    file: {video}\n    start_offset_s: -1\n"
    )

    with pytest.raises(ValidationError):
        load_manifest(manifest_path)
