"""Correlation groups (P3-J3, design_architecture.md §9): events linked across cameras. Read
only — the correlation service owns the writes. Any authenticated role may read; alerts are
operator-only but the story of an incident is not.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import User

from api.adapters.groups import get_group, links_for_group, list_groups
from api.api.deps import get_session
from api.api.errors import APIError
from api.api.security import get_current_user
from api.schemas import CorrelationGroupDetail, CorrelationGroupOut, CorrelationGroupsPage

router = APIRouter(prefix="/correlations", tags=["correlations"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _parse_uuid(value: str, *, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", f"Malformed {what} id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc


@router.get("", response_model=CorrelationGroupsPage)
async def list_correlations_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_user)],
    start: Annotated[
        AwareDatetime | None, Query(description="group window overlaps [start, end)")
    ] = None,
    end: Annotated[AwareDatetime | None, Query()] = None,
    site_id: str | None = None,
    group_status: Annotated[
        list[Literal["open", "closed", "merged"]] | None,
        Query(alias="status", description="default: open and closed (merged is history)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> CorrelationGroupsPage:
    if start is not None and end is not None and end <= start:
        raise APIError(
            "VALIDATION_ERROR", "end must be after start.", status_code=status.HTTP_400_BAD_REQUEST
        )
    rows = await list_groups(
        session,
        limit=limit + 1,
        cursor=_parse_uuid(cursor, what="cursor") if cursor else None,
        start=start,
        end=end,
        site_id=site_id,
        statuses=tuple(group_status) if group_status else ("open", "closed"),
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    return CorrelationGroupsPage(
        items=[CorrelationGroupOut.from_model(g) for g in page],
        next_cursor=str(page[-1].id) if has_more and page else None,
    )


@router.get("/{group_id}", response_model=CorrelationGroupDetail)
async def get_correlation_endpoint(
    group_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_user)],
) -> CorrelationGroupDetail:
    """A merged group is returned as it was (status `merged`, `merged_into` set) so a link to
    it keeps working; follow `merged_into` for the live group."""
    group = await get_group(session, _parse_uuid(group_id, what="group"))
    if group is None:
        raise APIError(
            "NOT_FOUND", "Correlation group not found.", status_code=status.HTTP_404_NOT_FOUND
        )
    return CorrelationGroupDetail.from_rows(group, await links_for_group(session, group.id))
