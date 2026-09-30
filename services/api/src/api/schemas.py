"""Service-local Pydantic models for api (not shared across services).

Cross-service contracts belong in libs/vms_common/contracts instead
(docs/style_guide.md §A.4). Fields follow §A.5: snake_case, ISO-8601 UTC
timestamps, ids as strings.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from vms_common.types import CameraCode, CameraId
from vms_db.models import Camera, Track, User, UserRole, Zone, ZoneType

from api.domain.recordings import DensityBucket, Gap, SegmentWindow
from api.domain.zones import validate_polygon

_RTSP_URL_PATTERN = re.compile(r"^rtsp://\S+$")  # FR-CAM-01: validate RTSP URL format


def _check_rtsp_url(value: str) -> str:
    if not _RTSP_URL_PATTERN.match(value):
        raise ValueError("rtsp_url must be a valid rtsp:// URL")
    return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 scheme name, not a secret
    expires_in: int


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    @classmethod
    def from_model(cls, user: User) -> UserOut:
        return cls(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )


class UsersPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UserOut]
    next_cursor: str | None = None


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)
    role: UserRole


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: UserRole | None = None
    is_active: bool | None = None


class CameraOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    code: CameraCode
    name: str
    rtsp_url: str
    site_id: str
    location_label: str | None
    lat: float | None
    lon: float | None
    enabled: bool
    created_at: datetime

    @classmethod
    def from_model(cls, camera: Camera) -> CameraOut:
        return cls(
            id=str(camera.id),
            code=camera.code,
            name=camera.name,
            rtsp_url=camera.rtsp_url,
            site_id=camera.site_id,
            location_label=camera.location_label,
            lat=camera.lat,
            lon=camera.lon,
            enabled=camera.enabled,
            created_at=camera.created_at,
        )


class CamerasPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CameraOut]
    next_cursor: str | None = None


class CameraCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: CameraCode = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    rtsp_url: str
    site_id: str = Field(min_length=1, max_length=100)
    location_label: str | None = Field(default=None, max_length=200)
    lat: float | None = None
    lon: float | None = None
    enabled: bool = True

    @field_validator("rtsp_url")
    @classmethod
    def _rtsp_url_is_valid(cls, value: str) -> str:
        return _check_rtsp_url(value)


class CameraUpdateRequest(BaseModel):
    """`name`/`rtsp_url`/`site_id`/`enabled` are non-nullable DB columns —
    the router rejects an explicit `null` for those (see
    `api.api.cameras._NON_NULLABLE_FIELDS`) rather than silently ignoring it
    or letting it reach the DB as a constraint violation. `location_label`/
    `lat`/`lon` are nullable, so `null` there is a legitimate "clear it".
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    rtsp_url: str | None = None
    site_id: str | None = Field(default=None, min_length=1, max_length=100)
    location_label: str | None = Field(default=None, max_length=200)
    lat: float | None = None
    lon: float | None = None
    enabled: bool | None = None

    @field_validator("rtsp_url")
    @classmethod
    def _rtsp_url_is_valid_if_set(cls, value: str | None) -> str | None:
        return _check_rtsp_url(value) if value is not None else value


class CameraStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    code: CameraCode
    name: str
    status: Literal["online", "reconnecting", "offline"]


class CamerasStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cameras: list[CameraStatusOut]


class SegmentItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["segment"] = "segment"
    segment_id: str
    start_ts: datetime
    end_ts: datetime
    uri: str

    @classmethod
    def from_domain(cls, seg: SegmentWindow) -> SegmentItemOut:
        return cls(segment_id=seg.segment_id, start_ts=seg.start_ts, end_ts=seg.end_ts, uri=seg.uri)


class GapItemOut(BaseModel):
    """An explicit marker for uncovered time (P2-J3 AC: "gaps return
    explicit markers instead of silent skips"), not a silently missing
    stretch of the requested range.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["gap"] = "gap"
    start_ts: datetime
    end_ts: datetime

    @classmethod
    def from_domain(cls, gap: Gap) -> GapItemOut:
        return cls(start_ts=gap.start_ts, end_ts=gap.end_ts)


class RecordingsSegmentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: CameraCode
    start: datetime
    end: datetime
    items: list[SegmentItemOut | GapItemOut]


class DensityBucketOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_ts: datetime
    end_ts: datetime
    count: int

    @classmethod
    def from_domain(cls, bucket: DensityBucket) -> DensityBucketOut:
        return cls(start_ts=bucket.start_ts, end_ts=bucket.end_ts, count=bucket.count)


class RecordingsDensityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: CameraCode
    start: datetime
    end: datetime
    bucket_seconds: int
    buckets: list[DensityBucketOut]


class OverlayObjectOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str
    category: str
    bbox: tuple[float, float, float, float]


class OverlayFrameOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: datetime
    objects: list[OverlayObjectOut]


class TwinFramesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: CameraCode
    start: datetime
    end: datetime
    frames: list[OverlayFrameOut]


class TrackSummaryOut(BaseModel):
    """Side-panel data for one clicked overlay box (P2-J6, FR-PLAY-03).
    `attributes_summary` is whatever subset of
    `vms_common.contracts.twin.ObjectAttributes` the twin populated for
    this category (colours only; never face data, per CLAUDE.md).
    """

    model_config = ConfigDict(extra="forbid")

    track_id: str
    camera_id: CameraCode
    category: str
    first_ts: datetime
    last_ts: datetime
    # Sum of vision.track_segments.dwell_s across every segment the track
    # appears in — vision.tracks itself only keeps first/last_ts (the
    # cross-segment span), not a dwell total, since a track can leave and
    # re-enter frame within that span.
    dwell_s: float
    zones_visited: list[str]
    attributes_summary: dict[str, str]

    @classmethod
    def from_model(cls, track: Track, *, dwell_s: float) -> TrackSummaryOut:
        return cls(
            track_id=track.track_id,
            camera_id=track.camera_id,
            category=track.category,
            first_ts=track.first_ts,
            last_ts=track.last_ts,
            dwell_s=dwell_s,
            zones_visited=list(track.zones_visited),
            attributes_summary=dict(track.attributes_summary),
        )


class ZoneScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: str = Field(pattern=r"^\d{2}:\d{2}$", description="HH:MM, site-local time")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$", description="HH:MM, site-local time")
    days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = Field(
        default_factory=lambda: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    )


class ZoneOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    # The UUID core.cameras.id, NOT the code — see api/zones.py's module docstring.
    camera_id: CameraId
    name: str
    zone_type: ZoneType
    polygon: list[tuple[float, float]]
    schedule: ZoneScheduleIn | None
    created_at: datetime

    @classmethod
    def from_model(cls, zone: Zone) -> ZoneOut:
        return cls(
            id=str(zone.id),
            camera_id=str(zone.camera_id),
            name=zone.name,
            zone_type=zone.zone_type,
            polygon=[tuple(p) for p in zone.polygon],
            schedule=ZoneScheduleIn.model_validate(zone.schedule) if zone.schedule else None,
            created_at=zone.created_at,
        )


class ZonesPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ZoneOut]


class ZoneCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    zone_type: ZoneType
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=32)
    schedule: ZoneScheduleIn | None = None

    @field_validator("polygon")
    @classmethod
    def _polygon_is_normalized(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return validate_polygon(value)


class ZoneUpdateRequest(BaseModel):
    """`name`/`zone_type`/`polygon` are non-nullable columns — the router
    rejects an explicit `null` for those (see `api.api.zones._NON_NULLABLE_FIELDS`),
    same reasoning as `CameraUpdateRequest`. `schedule` is nullable, so
    `null` there legitimately clears it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    zone_type: ZoneType | None = None
    polygon: list[tuple[float, float]] | None = Field(default=None, min_length=3, max_length=32)
    schedule: ZoneScheduleIn | None = None

    @field_validator("polygon")
    @classmethod
    def _polygon_is_normalized_if_set(
        cls, value: list[tuple[float, float]] | None
    ) -> list[tuple[float, float]] | None:
        return validate_polygon(value) if value is not None else value
