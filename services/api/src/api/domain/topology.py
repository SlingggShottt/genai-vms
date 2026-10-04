"""Camera-graph edge rules — no I/O (P3-J1 AC: "CRUD topology edges ... with
validation"). The same invariants `core.topology_edges` enforces with CHECK
constraints and `vms_common.contracts.topology.TopologyEdgeInternal` enforces on
the wire — duplicated here, not imported, since this is a request-validation
concern (style_guide.md §A.4) and the API should answer 400 with a readable
reason rather than surface a constraint violation.

Edge semantics (design_architecture.md §7.5):
- `overlap`: two cameras see the same area. Symmetric, so always bidirectional,
  and carries a `tolerance_s` (how far apart in time two events may be and still
  count as the same moment).
- `transit`: `to` is reachable from `from` in `min_s..max_s` seconds. One-way
  unless `bidirectional`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

EdgeKind = Literal["overlap", "transit"]

# Sanity ceilings, not physics: an hour of walking between two cameras, ten minutes of
# clock slack between two views of one scene. Anything bigger is a typo, and an
# unbounded window would link unrelated events.
MAX_TRANSIT_S = 3600.0
MAX_TOLERANCE_S = 600.0
DEFAULT_OVERLAP_TOLERANCE_S = 5.0


def validate_edge(
    edge_type: EdgeKind,
    *,
    min_s: float | None,
    max_s: float | None,
    tolerance_s: float | None,
    bidirectional: bool,
) -> None:
    """Raise `ValueError` (with a message fit to show a user) if the parameters do not
    suit the edge type."""
    if edge_type == "overlap":
        if tolerance_s is None:
            raise ValueError("an overlap edge needs tolerance_s")
        if min_s is not None or max_s is not None:
            raise ValueError("an overlap edge carries tolerance_s, not min_s/max_s")
        if not bidirectional:
            raise ValueError("an overlap edge is always bidirectional (overlap is symmetric)")
        if tolerance_s < 0 or tolerance_s > MAX_TOLERANCE_S:
            raise ValueError(f"tolerance_s must be between 0 and {MAX_TOLERANCE_S:g}")
        return
    if tolerance_s is not None:
        raise ValueError("a transit edge carries min_s/max_s, not tolerance_s")
    if min_s is None or max_s is None:
        raise ValueError("a transit edge needs both min_s and max_s")
    if min_s < 0 or max_s > MAX_TRANSIT_S:
        raise ValueError(f"min_s and max_s must lie between 0 and {MAX_TRANSIT_S:g} seconds")
    if max_s < min_s:
        raise ValueError("max_s must not be below min_s")


@dataclass(frozen=True)
class EdgeShape:
    """What conflict detection needs to know about an edge (an ORM row or a request)."""

    id: uuid.UUID | None
    from_camera_id: uuid.UUID
    to_camera_id: uuid.UUID
    edge_type: EdgeKind
    bidirectional: bool


def find_conflict(existing: Iterable[EdgeShape], candidate: EdgeShape) -> str | None:
    """Why `candidate` duplicates an edge already in the graph, or None if it is new.

    Compares against edges between the same two cameras (either direction); the edge
    with `candidate.id` (an edge being updated) is ignored.
    """
    for edge in existing:
        if edge.id is not None and edge.id == candidate.id:
            continue
        if edge.edge_type != candidate.edge_type:
            continue
        same_direction = (
            edge.from_camera_id == candidate.from_camera_id
            and edge.to_camera_id == candidate.to_camera_id
        )
        opposite = (
            edge.from_camera_id == candidate.to_camera_id
            and edge.to_camera_id == candidate.from_camera_id
        )
        if same_direction:
            return f"a {candidate.edge_type} edge between these cameras already exists"
        if not opposite:
            continue
        if candidate.edge_type == "overlap":
            return "an overlap edge between these cameras already exists (overlap is symmetric)"
        if edge.bidirectional:
            return "a bidirectional transit edge in the opposite direction already covers this"
        if candidate.bidirectional:
            return (
                "a transit edge in the opposite direction already exists; "
                "this bidirectional one would duplicate it"
            )
    return None
