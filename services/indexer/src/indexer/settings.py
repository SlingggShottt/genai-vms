"""IndexerSettings — Kafka/storage/DB blocks only (style_guide.md §A.1: no
`os.environ` in business code). The indexer has no model/behaviour config
of its own beyond consumer group naming.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from vms_common.config import (
    DatabaseSettings,
    KafkaSettings,
    QdrantSettings,
    StorageSettings,
    VMSBaseSettings,
)


class IndexerSettings(VMSBaseSettings):
    """`VMS_INDEXER_*` env vars, plus the shared Kafka/storage/DB blocks."""

    model_config = SettingsConfigDict(env_prefix="VMS_INDEXER_", env_file=".env", extra="ignore")

    consumer_group: str = Field(default="indexer")

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
