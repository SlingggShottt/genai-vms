"""Zone config shape for `GET /internal/v1/zones` (api -> perception, events —
an internal HTTP contract, same treatment as `camera.py`).

Landed with P2-J4 (`services/api/src/api/api/internal.py`); field names
match `core.zones` columns in design_architecture.md §6.1. `camera_id`
here is the camera's **code** (e.g. `cam03`), not `core.cameras.id` —
perception/events only ever see camera codes (from `segment.v1`), matching
`camera.py`'s own `CameraInternal.code` field. The public
`/cameras/{id}/zones` API (services/api) uses the UUID id instead, same
split as cameras.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vms_common.types import CameraCode

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ALL_WEEKDAYS: list[Weekday] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ZoneSchedule(BaseModel):
    """Active-schedule for a zone (e.g. after-hours, FR-EVT-01). Kept
    generic — exact recurrence rules can be refined by P2-J4/P3 if needed.
    """

    model_config = ConfigDict(extra="forbid")

    start_time: str = Field(description="HH:MM, site-local time")
    end_time: str = Field(description="HH:MM, site-local time")
    days: list[Weekday] = Field(default_factory=lambda: list(ALL_WEEKDAYS))


class ZoneInternal(BaseModel):
    """One zone as returned by the internal zones API."""

    model_config = ConfigDict(extra="forbid")

    id: str
    camera_id: CameraCode
    name: str
    zone_type: Literal["generic", "restricted", "entrance", "exit"]
    polygon: list[tuple[float, float]] = Field(
        min_length=3, max_length=32, description="normalized [[x,y], ...]"
    )
    schedule: ZoneSchedule | None = None

    @field_validator("polygon")
    @classmethod
    def _polygon_is_normalized(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for x, y in v:
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError(f"polygon points must be normalized to [0,1]: {v}")
        return v


class ZonesInternalResponse(BaseModel):
    """`GET /internal/v1/zones` response envelope."""

    model_config = ConfigDict(extra="forbid")

    zones: list[ZoneInternal] = Field(default_factory=list)
