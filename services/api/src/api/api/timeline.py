"""Investigation timeline (P6-J4, FR-INV-01): everything that happened in a period, by camera —
verified events, correlation groups and incident reports — in one response, so the UI can draw
lanes without a request per camera. Every role may read it (the story of an incident is not
operator-only; see `GET /correlations`)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime
from sqlalchemy import text
from vms_db.models import User

from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import get_current_user

router = APIRouter(prefix="/timeline", tags=["timeline"])

MAX_SPAN_HOURS = 24 * 7


@router.get("")
async def timeline(
    session: SessionDep,
    _user: Annotated[User, Depends(get_current_user)],
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
    cameras: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    if end <= start:
        raise APIError(
            "VALIDATION_ERROR", "end must be after start.", status_code=status.HTTP_400_BAD_REQUEST
        )
    if (end - start).total_seconds() > MAX_SPAN_HOURS * 3600:
        raise APIError(
            "VALIDATION_ERROR",
            f"The timeline covers at most {MAX_SPAN_HOURS // 24} days at a time.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    p = {"t0": start, "t1": end, "cams": cameras or None}
    events = (
        await session.execute(
            text(
                "SELECT e.id::text, e.camera_id, e.event_type, e.severity, e.start_ts, e.end_ts, "
                "e.verification->>'caption', a.id::text FROM events.events e "
                "LEFT JOIN core.alerts a ON a.event_id = e.id::text "
                "WHERE e.status <> 'rejected' AND e.end_ts >= :t0 AND e.start_ts < :t1 "
                "AND (CAST(:cams AS text[]) IS NULL OR e.camera_id = ANY(CAST(:cams AS text[]))) "
                "ORDER BY e.start_ts LIMIT 500"
            ),
            p,
        )
    ).all()
    incidents = (
        await session.execute(
            text(
                "SELECT id::text, title, severity, event_type, camera_ids, window_start, "
                "window_end FROM reasoning.incidents "
                "WHERE status IN ('generated', 'reviewed', 'closed') "
                "AND window_end >= :t0 AND window_start < :t1 "
                "AND (CAST(:cams AS text[]) IS NULL OR camera_ids && CAST(:cams AS text[])) "
                "ORDER BY window_start LIMIT 200"
            ),
            p,
        )
    ).all()
    groups = (
        await session.execute(
            text(
                "SELECT id::text, camera_ids, max_severity, start_ts, end_ts, "
                "cardinality(event_ids) FROM events.correlation_groups WHERE status <> 'merged' "
                "AND cardinality(camera_ids) > 1 AND end_ts >= :t0 AND start_ts < :t1 "
                "ORDER BY start_ts LIMIT 200"
            ),
            p,
        )
    ).all()
    seen = (
        await session.execute(
            text(
                "SELECT DISTINCT camera_id FROM media.segments WHERE end_ts >= :t0 AND start_ts < :t1"  # noqa: E501
            ),
            p,
        )
    ).all()

    def iso(ts: datetime) -> str:
        return ts.isoformat()

    return {
        "start": iso(start),
        "end": iso(end),
        "cameras": sorted({r[0] for r in seen} | {e[1] for e in events}),
        "events": [
            {
                "id": r[0],
                "camera_id": r[1],
                "event_type": r[2],
                "severity": r[3],
                "start": iso(r[4]),
                "end": iso(r[5]),
                "caption": r[6],
                "alert_id": r[7],
            }
            for r in events
        ],
        "incidents": [
            {
                "id": r[0],
                "title": r[1],
                "severity": r[2],
                "event_type": r[3],
                "camera_ids": list(r[4]),
                "start": iso(r[5]),
                "end": iso(r[6]),
            }
            for r in incidents
        ],
        "groups": [
            {
                "id": r[0],
                "camera_ids": list(r[1]),
                "severity": r[2],
                "start": iso(r[3]),
                "end": iso(r[4]),
                "events": r[5],
            }
            for r in groups
        ],
    }
