"""The messages pushed to browsers over the API's WebSocket (design_architecture.md §9).

    {"type": "job.progress", "data": {...}, "ts": "2026-10-25T10:16:14.512Z"}

Anything may publish one to the Redis channel `WS_CHANNEL` and every API replica forwards it to
the clients allowed to see that `type` (`api.domain.alerts.WS_MESSAGE_ROLES`). The envelope and the
two payloads the reasoning service sends live here because they cross a service boundary: the
reasoning worker produces them, the API relays them, the frontend reads them.

A message is a hint that something changed; the state itself is in Postgres. A client that missed
one (it was offline, Redis blinked) refetches, which is why publishing is best-effort.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from vms_common.contracts.event import Severity

WS_CHANNEL = "vms:ws:broadcast"
JOB_PROGRESS = "job.progress"
INCIDENT_READY = "incident.ready"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WsMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    data: dict[str, Any]
    ts: AwareDatetime = Field(default_factory=_utcnow)

    def to_json(self) -> str:
        return self.model_dump_json()


class JobProgressData(BaseModel):
    """One step of a reasoning job. `fraction` is 0 to 1; `stage` is the words an operator reads."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["running", "done", "failed"]
    stage: str
    fraction: float = Field(ge=0, le=1)
    group_id: str | None = None
    incident_id: str | None = None


class IncidentReadyData(BaseModel):
    """A report was written (or could not be)."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    group_id: str | None = None
    status: Literal["generated", "failed"]
    severity: Severity
    title: str


def job_progress(data: JobProgressData, *, ts: datetime | None = None) -> WsMessage:
    return WsMessage(type=JOB_PROGRESS, data=data.model_dump(mode="json"), **_at(ts))


def incident_ready(data: IncidentReadyData, *, ts: datetime | None = None) -> WsMessage:
    return WsMessage(type=INCIDENT_READY, data=data.model_dump(mode="json"), **_at(ts))


def _at(ts: datetime | None) -> dict[str, Any]:
    return {} if ts is None else {"ts": ts}
