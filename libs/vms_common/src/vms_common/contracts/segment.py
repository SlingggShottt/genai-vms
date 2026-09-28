"""segment.v1 — ingestion -> perception (design_architecture.md §5.3).

Announces one recorded segment. Video and keyframes are already in object
storage; this message carries only their `s3://` URIs (CLAUDE.md hard rule:
no video bytes on Kafka, messages stay under 1 MB).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, ValidationInfo, field_validator

from vms_common.contracts.base import MessageEnvelope


class SegmentV1(MessageEnvelope):
    """One camera's recorded segment, announced by ingestion on `vms.segments.v1`."""

    schema_version: Literal["segment.v1"] = "segment.v1"

    site_id: str
    camera_id: str
    segment_id: str = Field(description="{camera_id}_{start_utc}_{seq} (SRS §5)")

    start_ts: AwareDatetime
    end_ts: AwareDatetime

    uri: str = Field(description="s3:// URI of the MPEG-TS segment")
    keyframes_prefix: str = Field(description="s3:// prefix under which keyframes are stored")

    fps: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    codec: str

    gap_before: bool = Field(
        default=False, description="true if this segment follows a reconnect gap (FR-ING-05)"
    )

    @field_validator("uri", "keyframes_prefix")
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
