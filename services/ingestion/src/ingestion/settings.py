"""IngestionSettings — camera source, segment/keyframe config, and the
shared Kafka/storage/Redis blocks, all read via `vms_common.config`
(style_guide.md §A.1: no `os.environ` in business code).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from vms_common.config import KafkaSettings, RedisSettings, StorageSettings, VMSBaseSettings


def _default_work_dir() -> str:
    return str(Path(tempfile.gettempdir()) / "vms-ingestion")


class IngestionSettings(VMSBaseSettings):
    """`VMS_INGESTION_*` env vars, plus the shared Kafka/storage/Redis blocks."""

    model_config = SettingsConfigDict(env_prefix="VMS_INGESTION_", env_file=".env", extra="ignore")

    site_id: str = Field(default="rvce-campus")
    api_base_url: str | None = Field(
        default=None, description="e.g. http://api:8000/api/v1 (unset -> YAML fallback only)"
    )
    service_token: str = Field(default="")
    cameras_yaml_fallback: str = Field(default="config/cameras.yaml")
    camera_list_refresh_seconds: float = Field(default=60.0, gt=0)  # FR-CAM-05

    segment_seconds: int = Field(default=10, gt=0)  # FR-ING-02
    keyframe_fps: float = Field(default=1.0, gt=0)  # FR-ING-04
    work_dir: str = Field(default_factory=_default_work_dir)

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
