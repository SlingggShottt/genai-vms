"""Zone config shape for `GET /internal/v1/zones` (api -> perception, events —
an internal HTTP contract, same treatment as `camera.py`).

Proposed day 1 per design_architecture.md §16 ("Zones internal API | J (api)
| D (perception, events) — YAML fallback | P2 day 1 |
fixtures/zones_internal.json") so P2-D3 could build against a fixture
before P2-J4 (zones API) ships. Field names match `core.zones` columns in
design_architecture.md §6.1 — review/adjust together when P2-J4 lands.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    camera_id: str
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
