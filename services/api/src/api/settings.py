"""pydantic-settings configuration for api.

Config is read only through vms_common.config settings classes — never
os.environ directly (docs/style_guide.md §A.1).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from vms_common.config import DatabaseSettings, VMSBaseSettings


class ApiSettings(VMSBaseSettings):
    """`VMS_API_*` env vars, plus the shared database block."""

    model_config = SettingsConfigDict(env_prefix="VMS_API_", env_file=".env", extra="ignore")

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
