"""Per-camera sliding state of the rule engine (P3-D1 AC: "per-camera sliding
state (tracks, dwell, zone occupancy)") — pure, serializable.

The state is a set of **episodes**: for every (rule, zone, track-or-zone) the
engine is currently watching, the run of consecutive hits — when it started,
when it was last seen, how many frames, which tracks. That *is* the per-track
dwell in a zone (loitering), the zone's occupancy run (crowding) and the
frames-in-restricted-zone count (intrusion), without keeping any frame data.

It is plain Pydantic so the events service can checkpoint it per camera
(Redis) and resume after a restart without losing, say, a half-finished
loitering dwell.
"""

from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Episode(BaseModel):
    """One run of hits of one rule on one subject in one zone."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    event_type: str
    severity: str
    zone_id: str | None
    zone_name: str
    hit_key: str = Field(description="track id for per-track rules, '*' for zone-wide ones")

    first_ts: AwareDatetime
    last_ts: AwareDatetime
    frames: int = Field(ge=0, default=0, description="hit frames so far")
    score: float = 0.0
    track_ids: list[str] = Field(default_factory=list)
    segment_ids: list[str] = Field(default_factory=list)
    peaks: dict[str, float] = Field(default_factory=dict, description="per-episode maxima")
    params: dict[str, Any] = Field(default_factory=dict, description="effective params, last frame")

    candidate_id: str | None = Field(
        default=None,
        description="Set once the episode met its thresholds and became a candidate.",
    )

    @property
    def duration_s(self) -> float:
        return (self.last_ts - self.first_ts).total_seconds()


class CameraState(BaseModel):
    """Everything the engine remembers about one camera between twins."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    last_segment_end: AwareDatetime | None = Field(
        default=None,
        description="End of the last twin applied; older/equal twins are replays and are skipped.",
    )
    episodes: dict[str, Episode] = Field(default_factory=dict)
