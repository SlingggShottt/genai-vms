"""twinready.v1 — perception -> indexer, events (design_architecture.md §5.3).

Announces a segment's finished digital twin. The twin JSON and `.npz`
embeddings are already in object storage; this message carries only
their `s3://` URIs (CLAUDE.md: no video/heavy data on Kafka).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, ValidationInfo, field_validator

from vms_common.contracts.base import MessageEnvelope
from vms_common.types import CameraCode


class TwinReadyV1(MessageEnvelope):
    schema_version: Literal["twinready.v1"] = "twinready.v1"

    site_id: str
    camera_id: CameraCode
    segment_id: str
    start_ts: AwareDatetime
    end_ts: AwareDatetime

    twin_uri: str = Field(description="s3:// URI of the twin.v1 JSON document")
    embeddings_uri: str = Field(description="s3:// URI of the .npz embeddings")
    sample_fps: float = Field(gt=0)
    counts: dict[str, int] = Field(default_factory=dict, description="max count per category")
    track_ids: list[str] = Field(default_factory=list)
    perception_version: str = Field(description="e.g. yolo11s-bytetrack-siglip2b@0.3.0")

    @field_validator("twin_uri", "embeddings_uri")
    @classmethod
    def _must_be_s3_uri(cls, v: str) -> str:
        if not v.startswith("s3://"):
            raise ValueError(f"expected an s3:// uri, got {v!r}")
        return v

    @field_validator("end_ts")
    @classmethod
    def _end_after_start(cls, v: AwareDatetime, info: ValidationInfo) -> AwareDatetime:
        start = info.data.get("start_ts")
        if start is not None and v <= start:
            raise ValueError("end_ts must be after start_ts")
        return v
