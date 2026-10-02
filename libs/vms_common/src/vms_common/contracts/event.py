"""event.v1 — events -> correlation, indexer, api (design_architecture.md §5.3).

One *verified* event: a rule hit the VLM gate confirmed (`verification.status =
"verified"`), or one it was not asked about / could not be asked about
(`"skipped"` — `verify: false` rules, or the gateway being down for a low-severity
event, P3-D4). Rejected candidates are stored but never published.

Provided by Track D (the events service, P3-D4); consumed by correlation (P3-J2),
the api's alerts (P3-J3) and the indexer. Frozen day 1 of Phase 3 so those can be
built against the fixtures in `fixtures/event_v1_*.json` before the producer ships.

`event_type` is an open string (today: intrusion, loitering, crowding,
abandoned_object, running): a new rule must not break every consumer's parser, and
the consumers that care (correlation's compatibility matrix) decide what an unknown
type means. `camera_id` is the camera's code (design_architecture.md §5.1).
"""

from __future__ import annotations

import uuid
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from vms_common.contracts.base import MessageEnvelope
from vms_common.types import CameraCode

Severity = Literal["low", "medium", "high", "critical"]
SEVERITY_ORDER: tuple[Severity, ...] = ("low", "medium", "high", "critical")
VerificationStatus = Literal["verified", "skipped"]


def severity_rank(severity: str) -> int:
    """0 (low) .. 3 (critical); raises ValueError for anything else."""
    return SEVERITY_ORDER.index(severity)  # type: ignore[arg-type]


class Verification(BaseModel):
    """What the VLM gate concluded. Every field but `status` is absent when the gate was
    skipped."""

    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    confidence: float | None = Field(default=None, ge=0, le=1)
    caption: str | None = None
    model: str | None = Field(default=None, description="e.g. ollama/qwen2.5vl:3b")
    latency_ms: int | None = Field(default=None, ge=0)


class EventV1(MessageEnvelope):
    schema_version: Literal["event.v1"] = "event.v1"

    event_id: str
    site_id: str
    camera_id: CameraCode
    event_type: str = Field(min_length=1)
    severity: Severity
    start_ts: AwareDatetime
    end_ts: AwareDatetime

    rule_id: str = Field(description="e.g. intrusion.after_hours")
    rule_score: float = Field(ge=0, le=1)
    zone_id: str | None = Field(default=None, description="null for camera-wide rules")
    track_ids: list[str] = Field(default_factory=list)
    segment_ids: list[str] = Field(default_factory=list)
    keyframe_uris: list[str] = Field(default_factory=list)
    verification: Verification

    @field_validator("event_id")
    @classmethod
    def _event_id_is_a_uuid(cls, v: str) -> str:
        try:
            return str(uuid.UUID(v))
        except ValueError as exc:
            raise ValueError(f"event_id must be a UUID, got {v!r}") from exc

    @field_validator("keyframe_uris")
    @classmethod
    def _keyframes_are_s3_uris(cls, v: list[str]) -> list[str]:
        for uri in v:
            if not uri.startswith("s3://"):
                raise ValueError(f"expected s3:// uris, got {uri!r}")
        return v

    @model_validator(mode="after")
    def _window_is_not_inverted(self) -> Self:
        if self.end_ts < self.start_ts:
            raise ValueError("end_ts must not be before start_ts")
        return self
