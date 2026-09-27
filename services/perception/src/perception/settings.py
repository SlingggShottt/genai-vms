"""PerceptionSettings — model/device config, camera batching, zones source,
and the shared Kafka/storage/Redis blocks, all read via `vms_common.config`
(style_guide.md §A.1: no `os.environ` in business code).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from vms_common.config import KafkaSettings, RedisSettings, StorageSettings, VMSBaseSettings


def _default_work_dir() -> str:
    return str(Path(tempfile.gettempdir()) / "vms-perception")


class PerceptionSettings(VMSBaseSettings):
    """`VMS_PERCEPTION_*` env vars, plus the shared Kafka/storage/Redis blocks."""

    model_config = SettingsConfigDict(env_prefix="VMS_PERCEPTION_", env_file=".env", extra="ignore")

    site_id: str = Field(default="rvce-campus")

    # Zones source — same pattern as ingestion's camera source (design_architecture.md §16)
    api_base_url: str | None = Field(default=None, description="e.g. http://api:8000/api/v1")
    service_token: str = Field(default="")
    zones_yaml_fallback: str = Field(default="config/zones.yaml")
    zones_refresh_seconds: float = Field(default=60.0, gt=0)  # FR-CAM-05

    # Detection/tracking (FR-PER-01, NFR-PERF-01)
    model_name: str = Field(default="yolo11s.pt")
    device: str = Field(default="cuda:0", description="'cuda:0' or 'cpu'")
    detect_classes: list[str] = Field(
        default_factory=lambda: [
            "person",
            "bicycle",
            "car",
            "motorcycle",
            "bus",
            "truck",
            "backpack",
            "handbag",
            "suitcase",
        ]
    )
    confidence_threshold: float = Field(default=0.4, ge=0, le=1)
    max_batch_size: int = Field(default=8, gt=0)  # design_architecture.md §7.1: batch <= 8

    # Sampling (FR-PER-01, adaptive per P2-D1 AC)
    default_sample_fps: float = Field(default=2.0, gt=0)
    degraded_sample_fps: float = Field(default=1.0, gt=0)
    degrade_lag_threshold_s: float = Field(default=60.0, gt=0)
    recover_lag_threshold_s: float = Field(default=10.0, gt=0)

    # Embeddings (FR-PER-06)
    embedding_model_name: str = Field(default="google/siglip2-base-patch16-224")
    embedding_fps: float = Field(default=0.5, gt=0, description="every 2s by default (1/2.0)")

    work_dir: str = Field(default_factory=_default_work_dir)

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
