"""Events (design_architecture.md §9): what the VLM gate let through, listed and read. Read only —
the events service owns the writes; acting on one is an alert (`/alerts`) or an analysis
(`POST /events/{id}/analyze`, in `incidents.py`). Any authenticated role may read.

A `rejected` event (the VLM said no) is not listed unless `status=rejected` is asked for.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import AwareDatetime
from vms_db.models import User

from api.adapters.event_views import build_event_outs
from api.adapters.events import get_event, list_events
from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import get_current_user
from api.domain.events import EventCursor, MalformedCursorError
from api.schemas import EventOut, EventsPage

router = APIRouter(prefix="/events", tags=["events"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _bad_request(message: str) -> APIError:
    return APIError("VALIDATION_ERROR", message, status_code=status.HTTP_400_BAD_REQUEST)


@router.get("", response_model=EventsPage)
async def list_events_endpoint(
    session: SessionDep,
    _user: Annotated[User, Depends(get_current_user)],
    camera: Annotated[str | None, Query(description="camera code, e.g. cam02")] = None,
    event_type: Annotated[
        list[str] | None, Query(alias="type", description="repeat for several")
    ] = None,
    severity: Annotated[list[Literal["low", "medium", "high", "critical"]] | None, Query()] = None,
    event_status: Annotated[
        list[Literal["verified", "skipped", "rejected"]] | None,
        Query(alias="status", description="repeat for several; rejected is only shown if asked"),
    ] = None,
    start: Annotated[AwareDatetime | None, Query(description="event start >= start")] = None,
    end: Annotated[AwareDatetime | None, Query(description="event start < end")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> EventsPage:
    if start is not None and end is not None and end <= start:
        raise _bad_request("end must be after start.")
    try:
        after = EventCursor.decode(cursor) if cursor else None
    except MalformedCursorError as exc:
        raise _bad_request("Malformed cursor.") from exc
    rows = await list_events(
        session,
        limit=limit + 1,
        cursor=after,
        camera_code=camera,
        event_types=event_type or (),
        severities=severity or (),
        statuses=event_status or (),
        start=start,
        end=end,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    items = await build_event_outs(session, page)
    next_cursor = EventCursor(page[-1].start_ts, page[-1].id).encode() if has_more else None
    return EventsPage(items=items, next_cursor=next_cursor)


@router.get("/{event_id}", response_model=EventOut)
async def get_event_endpoint(
    event_id: str,
    request: Request,
    session: SessionDep,
    _user: Annotated[User, Depends(get_current_user)],
) -> EventOut:
    try:
        target = uuid.UUID(event_id)
    except ValueError as exc:
        raise _bad_request("Malformed event id.") from exc
    event = await get_event(session, target)
    if event is None:
        raise APIError("NOT_FOUND", "Event not found.", status_code=status.HTTP_404_NOT_FOUND)
    (out,) = await build_event_outs(session, [event], s3=request.app.state.s3)
    return out
