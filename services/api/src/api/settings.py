"""pydantic-settings configuration for api.

Config is read only through vms_common.config settings classes — never
os.environ directly (docs/style_guide.md §A.1).
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict
from vms_common.config import DatabaseSettings, JWTSettings, VMSBaseSettings


class AdminSeedSettings(VMSBaseSettings):
    """Seed admin account — `VMS_ADMIN_*` (P1-J2, FR-AUTH-04). Created on
    first start if no user with this email exists yet; see
    `api.adapters.users.seed_admin_user`.
    """

    model_config = SettingsConfigDict(env_prefix="VMS_ADMIN_", env_file=".env", extra="ignore")

    email: str = Field(default="admin@genai-vms.local")
    password: str = Field(default="")

    @field_validator("password")
    @classmethod
    def _password_meets_the_same_floor_as_every_other_account(cls, value: str) -> str:
        # Empty means "don't seed" (seed_admin_user's own no-op check) — the
        # one value this field allows despite the floor. Anything else must
        # meet the same bar UserCreateRequest enforces for every other
        # account; the admin is the highest-privilege one, not an exception.
        if value and len(value) < 8:
            raise ValueError(
                "VMS_ADMIN_PASSWORD must be empty (skip seeding) or at least 8 characters."
            )
        return value


class ApiSettings(VMSBaseSettings):
    """`VMS_API_*` env vars, plus the shared database/JWT blocks."""

    model_config = SettingsConfigDict(env_prefix="VMS_API_", env_file=".env", extra="ignore")

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    # Shared secret internal services present as `Authorization: Bearer
    # <token>` on /internal/* (design_architecture.md §15) — distinct from
    # user JWTs, not itself a JWT. Empty means "reject everything" (see
    # api.api.security.require_service_token), not "accept anything".
    service_token: str = Field(default="")

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    admin: AdminSeedSettings = Field(default_factory=AdminSeedSettings)
