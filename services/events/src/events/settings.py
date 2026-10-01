"""EventsSettings — rules file, site timezone, zones source and the shared
Kafka/storage/DB/Redis blocks, all read via `vms_common.config`
(style_guide.md §A.1: no `os.environ` in business code).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict
from vms_common.config import (
    DatabaseSettings,
    KafkaSettings,
    RedisSettings,
    StorageSettings,
    VMSBaseSettings,
)


class EventsSettings(VMSBaseSettings):
    """`VMS_EVENTS_*` env vars, plus the shared Kafka/storage/DB/Redis blocks."""

    model_config = SettingsConfigDict(env_prefix="VMS_EVENTS_", env_file=".env", extra="ignore")

    consumer_group: str = Field(default="events")

    rules_path: str = Field(default="config/rules.yaml", description="Rule thresholds + overrides")
    site_timezone: str = Field(
        default="Asia/Kolkata",
        description="IANA timezone zone schedules are written in (site-local HH:MM)",
    )

    # Zones source — same pattern as perception's (design_architecture.md §16)
    api_base_url: str | None = Field(default=None, description="e.g. http://api:8000/api/v1")
    service_token: str = Field(default="")
    zones_yaml_fallback: str = Field(default="config/zones.yaml")
    zones_refresh_seconds: float = Field(default=60.0, gt=0)  # FR-CAM-05

    state_ttl_seconds: int = Field(
        default=7 * 24 * 3600,
        gt=0,
        description="How long a silent camera's saved engine state is kept in Redis",
    )

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)

    @field_validator("site_timezone")
    @classmethod
    def _must_be_a_known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone {value!r}") from exc
        return value
