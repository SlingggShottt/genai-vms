"""Loads `config/camera_sim.yaml`: which video file each simulated camera
replays, and at what offset, so multi-view datasets (WILDTRACK/MEVA) stay
time-aligned (FR-ING-06, design_architecture.md §7.1, D-05).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CameraSource(BaseModel):
    """One simulated camera: a video file, and where to start playing it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    file: str
    start_offset_s: float = Field(default=0.0, ge=0.0)

    @field_validator("file")
    @classmethod
    def _file_must_exist(cls, v: str) -> str:
        if not Path(v).is_file():
            raise ValueError(
                f"video file not found: {v!r} (run ml/datasets/download/ first — P1-D6)"
            )
        return v


class SimManifest(BaseModel):
    """The full camera_sim manifest: where to publish, and what to publish."""

    model_config = ConfigDict(extra="forbid")

    mediamtx_url: str = Field(default="rtsp://localhost:8554")
    cameras: list[CameraSource]

    @field_validator("cameras")
    @classmethod
    def _unique_camera_ids(cls, v: list[CameraSource]) -> list[CameraSource]:
        ids = [c.id for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate camera ids in manifest: {ids}")
        return v

    @field_validator("cameras")
    @classmethod
    def _at_least_one_camera(cls, v: list[CameraSource]) -> list[CameraSource]:
        if not v:
            raise ValueError("manifest must declare at least one camera")
        return v


def load_manifest(path: str | Path) -> SimManifest:
    """Load and validate a camera_sim manifest from `path`."""
    raw = yaml.safe_load(Path(path).read_text())
    return SimManifest.model_validate(raw)
