"""twin.v1 — the digital twin document for one segment (design_architecture.md §7.2).

Written by perception to S3 (`vms-twins` bucket); `twinready.v1` on Kafka
carries only its URI (see `twinready.py`) — this model itself never
travels on Kafka, so it doesn't inherit `MessageEnvelope`. Bboxes are
normalized `[x1, y1, x2, y2]`. Masks are **not** included — SAM 2.1 masks
are produced on demand (design_architecture.md §10.2), not per twin.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from vms_common.types import CameraCode


class FrameSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    w: int = Field(gt=0)
    h: int = Field(gt=0)


class ObjectAttributes(BaseModel):
    """Colour attributes (FR-PER-04): persons get upper/lower, everything
    else gets a single `color`. All optional — not every category has
    every attribute, and attributes may be unavailable (e.g. occluded).
    """

    model_config = ConfigDict(extra="forbid")

    upper_color: str | None = None
    lower_color: str | None = None
    color: str | None = None


class ObjectMotion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speed: float = Field(ge=0, description="normalized units/s")
    direction_deg: float = Field(ge=0, lt=360)


class FrameObject(BaseModel):
    """One detected+tracked object in one sampled frame."""

    model_config = ConfigDict(extra="forbid")

    track_id: str
    category: str
    conf: float = Field(ge=0, le=1)
    bbox: tuple[float, float, float, float] = Field(
        description="normalized (x1, y1, x2, y2), x1<x2 and y1<y2"
    )
    attributes: ObjectAttributes = Field(default_factory=ObjectAttributes)
    motion: ObjectMotion | None = None
    zones: list[str] = Field(default_factory=list)

    @field_validator("bbox")
    @classmethod
    def _bbox_is_normalized_and_ordered(
        cls, v: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = v
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError(f"bbox must be normalized with x1<x2, y1<y2: {v}")
        return v


class Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: AwareDatetime
    idx: int = Field(ge=0)
    keyframe_uri: str
    objects: list[FrameObject] = Field(default_factory=list)

    @field_validator("keyframe_uri")
    @classmethod
    def _must_be_s3_uri(cls, v: str) -> str:
        if not v.startswith("s3://"):
            raise ValueError(f"expected an s3:// uri, got {v!r}")
        return v


class TrackSummary(BaseModel):
    """One track's summary across the whole segment."""

    model_config = ConfigDict(extra="forbid")

    track_id: str
    category: str
    first_ts: AwareDatetime
    last_ts: AwareDatetime
    dwell_s: float = Field(ge=0)
    zones_visited: list[str] = Field(default_factory=list)
    attributes_summary: ObjectAttributes = Field(default_factory=ObjectAttributes)
    best_crop_uri: str
    embedding_index: int = Field(ge=0, description="index into embeddings_uri's track_vectors")

    @field_validator("best_crop_uri")
    @classmethod
    def _must_be_s3_uri(cls, v: str) -> str:
        if not v.startswith("s3://"):
            raise ValueError(f"expected an s3:// uri, got {v!r}")
        return v


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_count_max: int = Field(ge=0, default=0)
    vehicle_count_max: int = Field(ge=0, default=0)


class TwinV1(BaseModel):
    """The full digital twin document for one segment."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["twin.v1"] = "twin.v1"

    segment_id: str
    camera_id: CameraCode
    site_id: str
    start_ts: AwareDatetime
    end_ts: AwareDatetime
    sample_fps: float = Field(gt=0)
    frame_size: FrameSize

    frames: list[Frame] = Field(default_factory=list)
    tracks: list[TrackSummary] = Field(default_factory=list)
    scene: Scene = Field(default_factory=Scene)
