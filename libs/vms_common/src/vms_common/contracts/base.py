"""Shared envelope fields for every Kafka message contract.

design_architecture.md §5.1: every message has `schema_version`,
`message_id` (UUIDv7) and `produced_at` (UTC). `schema_version` is a
`Literal` declared on each concrete contract, not here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from vms_common.ids import uuid7_str


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MessageEnvelope(BaseModel):
    """Base class for every contract that travels on Kafka."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=uuid7_str)
    produced_at: AwareDatetime = Field(default_factory=_utcnow)
