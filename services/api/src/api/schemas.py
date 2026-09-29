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
from vms_db.models import Camera, User, UserRole

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
    code: str
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

    code: str = Field(min_length=1, max_length=50)
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
    code: str
    name: str
    status: Literal["online", "reconnecting", "offline"]


class CamerasStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cameras: list[CameraStatusOut]
