"""pydantic-settings configuration for reasoning (`VMS_REASONING_*`).

Config is read only through vms_common.config settings classes — never os.environ directly
(docs/style_guide.md §A.1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from vms_common.config import (
    DatabaseSettings,
    KafkaSettings,
    RedisSettings,
    StorageSettings,
    VMSBaseSettings,
)


class ReasoningSettings(VMSBaseSettings):
    model_config = SettingsConfigDict(env_prefix="VMS_REASONING_", env_file=".env", extra="ignore")

    log_level: str = "INFO"
    poll_s: float = Field(default=2.0, gt=0)
    # A running job whose worker died becomes claimable again after this long. Every step renews
    # it, and a single model call is bounded by the gateway's 120 s timeout, so 5 minutes is safe.
    job_lease_s: float = Field(default=300.0, gt=0)

    # The synced window around an incident (design §8.1: -15 s … +15 s).
    pad_before_s: float = Field(default=15.0, ge=0)
    pad_after_s: float = Field(default=15.0, ge=0)

    # What the local 4 GB GPU can carry per call: ~1,050 prompt tokens per image (models.yaml).
    max_views: int = Field(default=2, ge=1, le=4)
    phase_frames: int = Field(default=5, ge=3, le=8)  # frames shown to the phase-location step
    frames_per_view: int = Field(default=2, ge=1, le=4)  # frames shown per phase × camera
    questions_per_view: int = Field(default=4, ge=0, le=8)
    synthesis_retries: int = Field(default=2, ge=0, le=3)

    # Closed correlation groups at or above this severity are analysed without anyone asking.
    auto_enabled: bool = True
    auto_min_severity: Literal["low", "medium", "high", "critical"] = "high"
    auto_max_per_hour: int = Field(default=6, ge=0)
    correlations_topic: str = "vms.correlations.v1"
    incidents_topic: str = "vms.incidents.v1"
    consumer_group: str = "reasoning-auto"

    vqa_bank_path: str = "config/vqa_bank.yaml"

    # Daily reports: the worker queues yesterday's report once the site clock passes this hour
    # (the design's supercronic / CronJob, without a second container to run it).
    site_timezone: str = "Asia/Kolkata"
    daily_report_hour: int = Field(default=6, ge=0, le=23)
    daily_report_auto: bool = True
    evidence_bucket: str = "vms-evidence"

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
