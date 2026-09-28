"""Camera config shape for `GET /internal/v1/cameras` (api -> ingestion,
perception, events — an internal HTTP contract, not a Kafka message, but
still a cross-service boundary per CLAUDE.md's contract rule).

Proposed day 1 per design_architecture.md §16 ("Camera internal API |
J (api) | D (ingestion) — YAML fallback | P1 day 1 |
fixtures/cameras_internal.json"), written from the ingestion side so
P1-D5 can build against a fixture before P1-J3 (camera management API)
ships. Field names match `core.cameras` columns in design_architecture.md
§6.1 — review/adjust together when P1-J3 lands.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CameraInternal(BaseModel):
    """One camera as returned by the internal cameras API."""

    model_config = ConfigDict(extra="forbid")

    id: str
    code: str
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
