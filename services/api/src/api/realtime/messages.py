"""The envelope of every WebSocket message (design_architecture.md §9).

    {"type": "alert.created", "data": {...}, "ts": "2026-10-05T10:16:14.512Z"}

`type` is one of `alert.created`, `alert.updated`, `camera.status`, `job.progress`,
`incident.ready`; who may receive which is `api.domain.alerts.WS_MESSAGE_ROLES`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WsMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    data: dict[str, Any]
    ts: AwareDatetime = Field(default_factory=_utcnow)

    def to_json(self) -> str:
        return self.model_dump_json()
