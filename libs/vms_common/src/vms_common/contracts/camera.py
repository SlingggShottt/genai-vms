"""Camera config shape for `GET /internal/v1/cameras` (api -> ingestion,
perception, events — an internal HTTP contract, not a Kafka message, but
still a cross-service boundary per CLAUDE.md's contract rule).

Landed with P1-J3 (`services/api/src/api/api/internal.py`); field names
match `core.cameras` columns in design_architecture.md §6.1. `id` and
`code` are genuinely different identifiers (design_architecture.md §5.1) —
`code` is what every Kafka message and every other internal contract calls
`camera_id`; `id` is the UUID the public REST API keys on instead.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vms_common.types import CameraCode, CameraId


class CameraInternal(BaseModel):
    """One camera as returned by the internal cameras API."""

    model_config = ConfigDict(extra="forbid")

    id: CameraId
    code: CameraCode
    name: str
    rtsp_url: str
    site_id: str
    location_label: str | None = None
    lat: float | None = None
    lon: float | None = None
    enabled: bool = True


class CamerasInternalResponse(BaseModel):
    """`GET /internal/v1/cameras` response envelope."""

    model_config = ConfigDict(extra="forbid")

    cameras: list[CameraInternal] = Field(default_factory=list)
