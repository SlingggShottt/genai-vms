"""Camera-graph (topology) endpoints (FR-CAM-04) — the edges the correlation service
links events across (design_architecture.md §7.5). Read: any authenticated role.
Write: admin only.

`from_camera_id` / `to_camera_id` here are `core.cameras.id`, the UUIDs — matching every
other resource id this API exposes. `GET /internal/v1/topology` (`api/internal.py`) reports
the cameras' **codes** instead, which is what correlation sees in `event.v1`
(design_architecture.md §5.1).

An edge's cameras and type are its identity: PATCH changes only its parameters
(`min_s`/`max_s`/`tolerance_s`/`bidirectional`); to change anything else, delete and
recreate. Both cameras must exist and belong to the same site — correlation groups are
per site, so an edge across sites could never be used.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError
from vms_db.models import TopologyEdge, User, UserRole

from api.adapters.cameras import get_camera_by_id
from api.adapters.topology import (
    create_edge,
    delete_edge,
    edges_between,
    get_edge_by_id,
    list_edges,
    update_edge,
)
from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import get_current_user, require_role
from api.domain.topology import EdgeShape, find_conflict, validate_edge
from api.schemas import (
    TopologyEdgeCreateRequest,
    TopologyEdgeOut,
    TopologyEdgesPage,
    TopologyEdgeUpdateRequest,
)

router = APIRouter(prefix="/topology", tags=["topology"])

_admin_only = require_role(UserRole.ADMIN)


def _parse_uuid(value: str, *, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", f"Malformed {what} id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc


def _conflict(message: str) -> APIError:
    return APIError(
        "CONFLICT", message[0].upper() + message[1:] + ".", status_code=status.HTTP_409_CONFLICT
    )


def _shape(edge: TopologyEdge) -> EdgeShape:
    return EdgeShape(
        id=edge.id,
        from_camera_id=edge.from_camera_id,
        to_camera_id=edge.to_camera_id,
        edge_type=edge.edge_type.value,
        bidirectional=edge.bidirectional,
    )


@router.get("/edges", response_model=TopologyEdgesPage)
async def list_edges_endpoint(
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_user)],
    camera_id: Annotated[str | None, Query(description="only edges touching this camera")] = None,
) -> TopologyEdgesPage:
    wanted = _parse_uuid(camera_id, what="camera") if camera_id else None
    edges = await list_edges(session, camera_id=wanted)
    return TopologyEdgesPage(items=[TopologyEdgeOut.from_model(e) for e in edges])


@router.post("/edges", response_model=TopologyEdgeOut, status_code=status.HTTP_201_CREATED)
async def create_edge_endpoint(
    body: TopologyEdgeCreateRequest,
    session: SessionDep,
    _admin: Annotated[User, Depends(_admin_only)],
) -> TopologyEdgeOut:
    from_id, to_id = uuid.UUID(body.from_camera_id), uuid.UUID(body.to_camera_id)
    from_camera = await get_camera_by_id(session, from_id)
    to_camera = await get_camera_by_id(session, to_id)
    if from_camera is None or to_camera is None:
        raise APIError(
            "NOT_FOUND",
            "Camera not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"field": "from_camera_id" if from_camera is None else "to_camera_id"},
        )
    if from_camera.site_id != to_camera.site_id:
        raise APIError(
            "VALIDATION_ERROR",
            "Cameras must belong to the same site; correlation groups are per site.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    conflict = find_conflict(
        [_shape(e) for e in await edges_between(session, from_id, to_id)],
        EdgeShape(
            id=None,
            from_camera_id=from_id,
            to_camera_id=to_id,
            edge_type=body.edge_type.value,
            bidirectional=bool(body.bidirectional),
        ),
    )
    if conflict:
        raise _conflict(conflict)

    try:
        edge = await create_edge(
            session,
            from_camera_id=from_id,
            to_camera_id=to_id,
            edge_type=body.edge_type,
            min_s=body.min_s,
            max_s=body.max_s,
            tolerance_s=body.tolerance_s,
            bidirectional=bool(body.bidirectional),
        )
    except IntegrityError as exc:
        # The precheck does not rule out a concurrent request creating the same edge between
        # the check and this insert; the unique constraint / index is the real guard.
        raise _conflict("an edge between these cameras already exists") from exc
    return TopologyEdgeOut.from_model(edge)


@router.patch("/edges/{edge_id}", response_model=TopologyEdgeOut)
async def update_edge_endpoint(
    edge_id: str,
    body: TopologyEdgeUpdateRequest,
    session: SessionDep,
    _admin: Annotated[User, Depends(_admin_only)],
) -> TopologyEdgeOut:
    edge = await get_edge_by_id(session, _parse_uuid(edge_id, what="edge"))
    if edge is None:
        raise APIError("NOT_FOUND", "Edge not found.", status_code=status.HTTP_404_NOT_FOUND)

    changes = body.model_dump(exclude_unset=True)
    if "bidirectional" in changes and changes["bidirectional"] is None:
        raise APIError(
            "VALIDATION_ERROR",
            "bidirectional cannot be null.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    merged = {
        "min_s": edge.min_s,
        "max_s": edge.max_s,
        "tolerance_s": edge.tolerance_s,
        "bidirectional": edge.bidirectional,
    } | changes
    try:
        validate_edge(edge.edge_type.value, **merged)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", f"{exc}.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc

    if merged["bidirectional"] != edge.bidirectional:
        conflict = find_conflict(
            [
                _shape(e)
                for e in await edges_between(session, edge.from_camera_id, edge.to_camera_id)
            ],
            EdgeShape(
                id=edge.id,
                from_camera_id=edge.from_camera_id,
                to_camera_id=edge.to_camera_id,
                edge_type=edge.edge_type.value,
                bidirectional=bool(merged["bidirectional"]),
            ),
        )
        if conflict:
            raise _conflict(conflict)

    edge = await update_edge(session, edge, changes)
    return TopologyEdgeOut.from_model(edge)


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edge_endpoint(
    edge_id: str,
    session: SessionDep,
    _admin: Annotated[User, Depends(_admin_only)],
) -> None:
    edge = await get_edge_by_id(session, _parse_uuid(edge_id, what="edge"))
    if edge is None:
        raise APIError("NOT_FOUND", "Edge not found.", status_code=status.HTTP_404_NOT_FOUND)
    await delete_edge(session, edge)
