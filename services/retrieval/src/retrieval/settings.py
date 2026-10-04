"""pydantic-settings configuration for retrieval (`VMS_RETRIEVAL_*`).

Config is read only through vms_common.config settings classes — never os.environ directly
(docs/style_guide.md §A.1).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from vms_common.config import (
    DatabaseSettings,
    QdrantSettings,
    RedisSettings,
    StorageSettings,
    VMSBaseSettings,
)


class RetrievalSettings(VMSBaseSettings):
    model_config = SettingsConfigDict(env_prefix="VMS_RETRIEVAL_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"  # noqa: S104 - a service port, reached through the api
    port: int = 8010
    log_level: str = "INFO"

    # SigLIP 2 text/image encoder; CPU keeps the 4 GB GPU for the VLMs (design §10.1).
    siglip_model: str = "google/siglip2-base-patch16-224"
    encoder_device: str = "cpu"

    site_timezone: str = "Asia/Kolkata"
    # Recordings and keyframes are removed by the retention policy while the index can outlive
    # them; footage older than this is not searched (and so is not offered as a result whose
    # picture is gone). Unset = search everything.
    archive_since: datetime | None = None
    # Per-collection raw hits per query vector, before fusion.
    hits_per_query: int = Field(default=80, ge=10, le=500)
    # Hits closer than this on one camera are one candidate window (design §10.1).
    window_s: float = Field(default=10.0, gt=0)
    # `reason` mode: how many fused candidates the LLM rereads, and how many per call.
    rerank_top_n: int = Field(default=10, ge=1, le=30)
    rerank_batch: int = Field(default=5, ge=1, le=10)
    # Final = (1 - w) * fused + w * reasoning.
    reasoning_weight: float = Field(default=0.6, ge=0, le=1)
    # Hard stop for the whole LLM part of one search, so a slow GPU degrades to the fast result.
    llm_budget_s: float = Field(default=75.0, gt=0)
    decompose_budget_s: float = Field(default=25.0, gt=0)

    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
