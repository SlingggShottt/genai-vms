"""Topology repository — SQLAlchemy queries against `core.topology_edges`. No
business rules here (validation, conflicts, permissions); that's the domain's and
the router's job.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import EdgeType, TopologyEdge


async def get_edge_by_id(session: AsyncSession, edge_id: uuid.UUID) -> TopologyEdge | None:
    return await session.get(TopologyEdge, edge_id)


async def list_edges(
    session: AsyncSession, *, camera_id: uuid.UUID | None = None
) -> list[TopologyEdge]:
    """Every edge, or only those touching `camera_id` (either end), oldest first."""
    stmt = select(TopologyEdge).order_by(TopologyEdge.id)
    if camera_id is not None:
        stmt = stmt.where(
            or_(TopologyEdge.from_camera_id == camera_id, TopologyEdge.to_camera_id == camera_id)
        )
    return list((await session.execute(stmt)).scalars().all())


async def list_all_edges(session: AsyncSession) -> list[TopologyEdge]:
    """The whole graph — for `/internal/v1/topology`."""
    return await list_edges(session)


async def edges_between(
    session: AsyncSession, camera_a: uuid.UUID, camera_b: uuid.UUID
) -> list[TopologyEdge]:
    """Edges joining the two cameras in either direction — for conflict detection."""
    stmt = select(TopologyEdge).where(
        or_(
            (TopologyEdge.from_camera_id == camera_a) & (TopologyEdge.to_camera_id == camera_b),
            (TopologyEdge.from_camera_id == camera_b) & (TopologyEdge.to_camera_id == camera_a),
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_edge(
    session: AsyncSession,
    *,
    from_camera_id: uuid.UUID,
    to_camera_id: uuid.UUID,
    edge_type: EdgeType,
    min_s: float | None,
    max_s: float | None,
    tolerance_s: float | None,
    bidirectional: bool,
) -> TopologyEdge:
    edge = TopologyEdge(
        from_camera_id=from_camera_id,
        to_camera_id=to_camera_id,
        edge_type=edge_type,
        min_s=min_s,
        max_s=max_s,
        tolerance_s=tolerance_s,
        bidirectional=bidirectional,
    )
    session.add(edge)
    await session.flush()  # populates server-generated defaults (created_at) for the caller
    return edge


UPDATABLE_FIELDS = frozenset({"min_s", "max_s", "tolerance_s", "bidirectional"})


async def update_edge(
    session: AsyncSession, edge: TopologyEdge, changes: dict[str, object]
) -> TopologyEdge:
    """Apply exactly the fields in `changes` (e.g. `TopologyEdgeUpdateRequest.model_dump(
    exclude_unset=True)`). An explicit `null` is applied, not skipped: whether the result is
    still a valid edge is the caller's check, made before this is called.
    """
    for field, value in changes.items():
        if field in UPDATABLE_FIELDS:
            setattr(edge, field, value)
    await session.flush()  # surface a constraint violation here, inside the request
    return edge


async def delete_edge(session: AsyncSession, edge: TopologyEdge) -> None:
    await session.delete(edge)
