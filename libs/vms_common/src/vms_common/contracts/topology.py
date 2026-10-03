"""Camera-graph shape for `GET /internal/v1/topology` (api -> correlation — an
internal HTTP contract, same treatment as `camera.py` and `zones.py`).

Landed with P3-J1 (`services/api/src/api/api/internal.py`); field names match
`core.topology_edges` in design_architecture.md §6.1. `from_camera_id` /
`to_camera_id` are the cameras' **codes** (e.g. `cam03`), not `core.cameras.id`:
correlation only ever sees codes (from `event.v1`), as with every other internal
contract (design_architecture.md §5.1). The public `/topology/edges` API uses the
UUIDs instead.

Edge semantics (design_architecture.md §7.5):
- `overlap`: the cameras see the same area; always two-way; carries `tolerance_s`.
- `transit`: `to` is reachable from `from` in `min_s..max_s` seconds; carries that
  window; two-way only when `bidirectional`.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms_common.types import CameraCode

EdgeType = Literal["overlap", "transit"]


class TopologyEdgeInternal(BaseModel):
    """One edge of the camera graph. The same rules the database enforces on
    `core.topology_edges`, so a consumer can trust what it parses.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    from_camera_id: CameraCode
    to_camera_id: CameraCode
    edge_type: EdgeType
    min_s: float | None = Field(default=None, ge=0)
    max_s: float | None = Field(default=None, ge=0)
    tolerance_s: float | None = Field(default=None, ge=0)
    bidirectional: bool = False

    @model_validator(mode="after")
    def _parameters_match_the_edge_type(self) -> Self:
        if self.from_camera_id == self.to_camera_id:
            raise ValueError("an edge must connect two different cameras")
        if self.edge_type == "overlap":
            if self.tolerance_s is None:
                raise ValueError("an overlap edge needs tolerance_s")
            if self.min_s is not None or self.max_s is not None:
                raise ValueError("an overlap edge carries tolerance_s, not min_s/max_s")
            if not self.bidirectional:
                raise ValueError("an overlap edge is always bidirectional")
        else:
            if self.min_s is None or self.max_s is None:
                raise ValueError("a transit edge needs min_s and max_s")
            if self.tolerance_s is not None:
                raise ValueError("a transit edge carries min_s/max_s, not tolerance_s")
            if self.max_s < self.min_s:
                raise ValueError("max_s must not be below min_s")
        return self


class TopologyInternalResponse(BaseModel):
    """`GET /internal/v1/topology` response envelope."""

    model_config = ConfigDict(extra="forbid")

    edges: list[TopologyEdgeInternal] = Field(default_factory=list)
