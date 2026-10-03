"""Alert endpoints (P3-J3, FR-ALR-01/02): list, read, acknowledge, resolve. Operator and
above — a viewer sees no alert traffic (design_architecture.md §9).

Acknowledge and resolve are single conditional UPDATEs (`adapters/alerts.py`): of two operators
acting at once exactly one wins and the other gets 409 with the status it found. Each success is
audited (`alert.acknowledged` / `alert.resolved`, the note in `details`) and pushed to every
dashboard as `alert.updated` — after the commit, so a client that refetches sees the new state.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import User, UserRole
from vms_db.session import session_scope

from api.adapters.alert_views import build_alert_outs
from api.adapters.alerts import acknowledge, get_alert, list_alerts, resolve
from api.adapters.audit import write_audit_log
from api.api.deps import get_session
from api.api.errors import APIError
from api.api.security import require_role
from api.domain.alerts import AlertTransitionError, check_transition
from api.metrics import alert_actions_total
from api.realtime.messages import WsMessage
from api.realtime.publish import publish_best_effort
from api.schemas import AlertActionRequest, AlertOut, AlertsPage

router = APIRouter(prefix="/alerts", tags=["alerts"])

_operator_up = require_role(UserRole.ADMIN, UserRole.OPERATOR)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _parse_uuid(value: str, *, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", f"Malformed {what} id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc


def _not_found() -> APIError:
    return APIError("NOT_FOUND", "Alert not found.", status_code=status.HTTP_404_NOT_FOUND)


@router.get("", response_model=AlertsPage)
async def list_alerts_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(_operator_up)],
    alert_status: Annotated[
        list[Literal["open", "acknowledged", "resolved"]] | None,
        Query(alias="status", description="repeat for several"),
    ] = None,
    severity: Annotated[list[Literal["low", "medium", "high", "critical"]] | None, Query()] = None,
    camera_id: Annotated[str | None, Query(description="camera code, e.g. cam02")] = None,
    group_id: Annotated[str | None, Query(description="correlation group")] = None,
    start: Annotated[AwareDatetime | None, Query(description="event start >= start")] = None,
    end: Annotated[AwareDatetime | None, Query(description="event start < end")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> AlertsPage:
    if start is not None and end is not None and end <= start:
        raise APIError(
            "VALIDATION_ERROR", "end must be after start.", status_code=status.HTTP_400_BAD_REQUEST
        )
    rows = await list_alerts(
        session,
        limit=limit + 1,
        cursor=_parse_uuid(cursor, what="cursor") if cursor else None,
        statuses=alert_status or (),
        severities=severity or (),
        camera_code=camera_id,
        group_id=_parse_uuid(group_id, what="group") if group_id else None,
        start=start,
        end=end,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    items = await build_alert_outs(session, page, s3=request.app.state.s3)
    return AlertsPage(items=items, next_cursor=str(page[-1].id) if has_more and page else None)


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert_endpoint(
    alert_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(_operator_up)],
) -> AlertOut:
    alert = await get_alert(session, _parse_uuid(alert_id, what="alert"))
    if alert is None:
        raise _not_found()
    (out,) = await build_alert_outs(session, [alert], s3=request.app.state.s3)
    return out


async def _act(
    request: Request,
    alert_id: str,
    body: AlertActionRequest | None,
    user: User,
    *,
    action: Literal["acknowledge", "resolve"],
) -> AlertOut:
    target = _parse_uuid(alert_id, what="alert")
    note = body.note if body else None
    move = acknowledge if action == "acknowledge" else resolve

    # Its own transaction, committed before the push and the audit entry below.
    async with session_scope(request.app.state.db_session_factory) as session:
        alert = await move(session, target, user_id=user.id, note=note)
        if alert is None:
            current = await get_alert(session, target)
            if current is None:
                raise _not_found()
            try:
                check_transition(action, current.status)
            except AlertTransitionError as exc:
                raise APIError(
                    "CONFLICT",
                    f"{str(exc).capitalize()}.",
                    status_code=status.HTTP_409_CONFLICT,
                    details={"status": current.status},
                ) from exc
            # Legal from the status read now, so it moved on in between: still a conflict.
            raise APIError(
                "CONFLICT",
                "The alert changed while you were acting on it; reload and try again.",
                status_code=status.HTTP_409_CONFLICT,
                details={"status": current.status},
            )
        (out,) = await build_alert_outs(session, [alert], s3=request.app.state.s3)

    alert_actions_total.labels(action=action).inc()
    await write_audit_log(
        request.app.state.db_session_factory,
        user_id=user.id,
        action=f"alert.{'acknowledged' if action == 'acknowledge' else 'resolved'}",
        entity_type="alert",
        entity_id=out.id,
        details={"event_id": out.event_id, "camera": out.camera_code, "note": note},
    )
    await publish_best_effort(
        request.app.state.relay,
        WsMessage(
            type="alert.updated",
            data=out.model_copy(update={"keyframe_urls": []}).model_dump(mode="json"),
        ),
    )
    return out


@router.post("/{alert_id}/ack", response_model=AlertOut)
async def acknowledge_alert_endpoint(
    alert_id: str,
    request: Request,
    user: Annotated[User, Depends(_operator_up)],
    body: AlertActionRequest | None = None,
) -> AlertOut:
    return await _act(request, alert_id, body, user, action="acknowledge")


@router.post("/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert_endpoint(
    alert_id: str,
    request: Request,
    user: Annotated[User, Depends(_operator_up)],
    body: AlertActionRequest | None = None,
) -> AlertOut:
    return await _act(request, alert_id, body, user, action="resolve")
