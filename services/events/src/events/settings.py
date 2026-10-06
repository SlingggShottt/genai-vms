"""EventsSettings — rules file, site timezone, zones source and the shared
Kafka/storage/DB/Redis blocks, all read via `vms_common.config`
(style_guide.md §A.1: no `os.environ` in business code).
"""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict
from vms_common.config import (
    DatabaseSettings,
    KafkaSettings,
    LLMSettings,
    RedisSettings,
    StorageSettings,
    VMSBaseSettings,
)

SeverityName = Literal["low", "medium", "high", "critical"]


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

    # The VLM verification gate (P3-D4; design §7.4, behaviour in events.domain.verification)
    events_topic: str = Field(default="vms.events.v1", description="Where event.v1 is published")
    verify_min_confidence: float = Field(default=0.6, ge=0, le=1)
    verify_unsure_accepted_up_to: SeverityName = Field(
        default="low",
        description="An 'unsure' answer is accepted (flagged) for rules at or below this severity",
    )
    verify_hold_from: SeverityName = Field(
        default="medium",
        description="With no model to ask, candidates at or above this severity wait for it",
    )
    verify_hold_max_age_seconds: float = Field(
        default=600.0, ge=0, description="...for at most this long, then are published unverified"
    )
    verify_batch_size: int = Field(default=4, ge=1)
    verify_poll_seconds: float = Field(default=2.0, gt=0)
    verify_lease_seconds: float = Field(
        default=300.0, gt=0, description="How long a claimed candidate is hidden from other workers"
    )
    verify_open_after_seconds: float = Field(
        default=90.0,
        ge=0,
        description="A candidate still going is judged once it has existed this long",
    )
    verify_max_age_seconds: float = Field(
        default=6 * 3600.0,
        gt=0,
        description="Candidates that ended longer ago than this are never judged (stale)",
    )
    verify_retry_base_seconds: float = Field(default=5.0, gt=0)
    verify_retry_cap_seconds: float = Field(default=300.0, gt=0)

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
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
