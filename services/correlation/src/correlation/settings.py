"""CorrelationSettings — topics, config files, topology source and the shared Kafka/DB blocks,
all read via `vms_common.config` (style_guide.md §A.1: no `os.environ` in business code)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from vms_common.config import DatabaseSettings, KafkaSettings, VMSBaseSettings


class CorrelationSettings(VMSBaseSettings):
    """`VMS_CORRELATION_*` env vars, plus the shared Kafka and DB blocks."""

    model_config = SettingsConfigDict(
        env_prefix="VMS_CORRELATION_", env_file=".env", extra="ignore"
    )

    consumer_group: str = Field(default="correlation")
    events_topic: str = Field(default="vms.events.v1")
    correlations_topic: str = Field(default="vms.correlations.v1")

    config_path: str = Field(default="config/correlation.yaml", description="Linking knobs")

    # Camera graph — same pattern as the events service's zones (design_architecture.md §16)
    api_base_url: str | None = Field(default=None, description="e.g. http://api:8000/api/v1")
    service_token: str = Field(default="")
    topology_yaml_fallback: str = Field(default="config/topology.yaml")
    topology_refresh_seconds: float = Field(default=60.0, gt=0)

    sweep_interval_seconds: float = Field(
        default=1.0,
        gt=0,
        description="How often open groups are checked for closing and changes are published",
    )

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
