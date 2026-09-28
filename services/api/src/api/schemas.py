"""Service-local Pydantic models for api (not shared across services).

Cross-service contracts belong in libs/vms_common/contracts instead
(docs/style_guide.md §A.4). Fields follow §A.5: snake_case, ISO-8601 UTC
timestamps, ids as strings.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from vms_db.models import User, UserRole


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
