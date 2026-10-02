"""correlation.v1 — correlation -> reasoning (orchestrator, P5), api alerts
(design_architecture.md §5.3, §7.5).

One message describes a *group* of events linked across cameras by the camera graph
and by time (or a single event nothing linked to). The group's whole current state is
in every message, so a consumer only ever needs the newest one:

- `open`   — still collecting events; re-sent as it grows (throttled to one per few
             seconds per group).
- `closed` — final. Nothing will be added; this is when reasoning should run.
- `merged` — final for *this* id: a later event bridged it with another group, and
             `merged_into` names the group that now holds all of its events. A consumer
             that acted on this group's `open` messages should fold them into that one.

`revision` increases on every change to a group, so a consumer can discard a message
older than one it has already seen (Kafka is at-least-once and a retry can reorder).
Provided by Track J (correlation, P3-J2). `camera_ids` are camera codes.
"""

from __future__ import annotations

import uuid
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from vms_common.contracts.base import MessageEnvelope
from vms_common.contracts.event import Severity
from vms_common.types import CameraCode

GroupStatus = Literal["open", "closed", "merged"]
LinkEdgeType = Literal["overlap", "transit"]


class CorrelationLink(BaseModel):
    """Why two events were put in the same group."""

    model_config = ConfigDict(extra="forbid")

    from_event: str
    to_event: str
    edge_type: LinkEdgeType
    delta_s: float = Field(
        description="transit: start of the later-camera event minus end of the earlier-camera "
        "event; overlap: the gap between the two windows (0 when they intersect)"
    )
    score: float = Field(ge=0, le=1)


class CorrelationV1(MessageEnvelope):
    schema_version: Literal["correlation.v1"] = "correlation.v1"

    group_id: str
    site_id: str
    status: GroupStatus
    revision: int = Field(ge=1)

    event_ids: list[str] = Field(min_length=1)
    camera_ids: list[CameraCode] = Field(min_length=1)
    event_types: list[str] = Field(default_factory=list)
    start_ts: AwareDatetime
    end_ts: AwareDatetime
    max_severity: Severity
    links: list[CorrelationLink] = Field(default_factory=list)
    merged_into: str | None = None

    @field_validator("group_id", "merged_into")
    @classmethod
    def _ids_are_uuids(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            return str(uuid.UUID(v))
        except ValueError as exc:
            raise ValueError(f"expected a UUID, got {v!r}") from exc

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.end_ts < self.start_ts:
            raise ValueError("end_ts must not be before start_ts")
        if (self.status == "merged") != (self.merged_into is not None):
            raise ValueError("merged_into is set if and only if status is 'merged'")
        if self.merged_into == self.group_id:
            raise ValueError("a group cannot be merged into itself")
        members = set(self.event_ids)
        for link in self.links:
            if link.from_event not in members or link.to_event not in members:
                raise ValueError("every link must join two events of the group")
        return self
