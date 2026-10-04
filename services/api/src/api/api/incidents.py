"""Incidents and reasoning jobs (P5-D4/P6-D1 on the api side, design §9): list and read the
reports the reasoning service wrote, edit status and notes, queue an analysis for an event, and
follow a job. The api never runs a model; it reads `reasoning.*` and inserts job rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from vms_common.ids import uuid7_str
from vms_db.models import Incident, ReasoningJob, User, UserRole

from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import get_current_user, require_role

router = APIRouter(tags=["incidents"])

_operator_up = require_role(UserRole.ADMIN, UserRole.OPERATOR)


class IncidentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    summary: str | None
    severity: str
    event_type: str
    status: str
    camera_ids: list[str]
    event_ids: list[str]
    group_id: str | None
    window_start: datetime
    window_end: datetime
    confidence: float | None
    created_at: datetime


class IncidentDetail(IncidentSummary):
    report: dict[str, Any] | None
    evidence: dict[str, Any] | None
    provenance: dict[str, Any]
    notes: str | None
    failure: str | None


class IncidentsPage(BaseModel):
    items: list[IncidentSummary]


class IncidentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["generated", "reviewed", "closed"] | None = None
    notes: str | None = Field(default=None, max_length=4000)


class JobOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    trigger: str
    status: str
    stage: str
    progress: float
    error: str | None
    incident_id: str | None
    group_id: str | None
    queue_position: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ReasoningState(BaseModel):
    """What the event page needs: the live job (if any) and the newest report (if any)."""

    model_config = ConfigDict(extra="forbid")

    job: JobOut | None
    incident: IncidentSummary | None


def _summary(row: Incident) -> IncidentSummary:
    report = row.report or {}
    return IncidentSummary(
        id=str(row.id),
        title=row.title,
        summary=report.get("summary"),
        severity=row.severity,
        event_type=row.event_type,
        status=row.status,
        camera_ids=list(row.camera_ids),
        event_ids=list(row.event_ids),
        group_id=str(row.group_id) if row.group_id else None,
        window_start=row.window_start,
        window_end=row.window_end,
        confidence=report.get("confidence"),
        created_at=row.created_at,
    )


async def _job_out(session, job: ReasoningJob) -> JobOut:
    position = None
    if job.status == "queued":
        position = (
            await session.execute(
                select(func.count())
                .select_from(ReasoningJob)
                .where(ReasoningJob.status == "queued", ReasoningJob.created_at < job.created_at)
            )
        ).scalar_one() + 1
    return JobOut(
        id=str(job.id),
        trigger=job.trigger,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        error=job.error,
        incident_id=str(job.incident_id) if job.incident_id else None,
        group_id=str(job.group_id) if job.group_id else None,
        queue_position=position,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", f"Malformed {what} id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc


@router.get("/incidents", response_model=IncidentsPage)
async def list_incidents(
    session: SessionDep,
    _user: Annotated[User, Depends(get_current_user)],
    incident_status: Annotated[
        list[Literal["generating", "generated", "failed", "reviewed", "closed"]] | None,
        Query(alias="status"),
    ] = None,
    severity: Annotated[list[Literal["low", "medium", "high", "critical"]] | None, Query()] = None,
    camera_id: str | None = None,
    event_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> IncidentsPage:
    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if incident_status:
        stmt = stmt.where(Incident.status.in_(incident_status))
    if severity:
        stmt = stmt.where(Incident.severity.in_(severity))
    if camera_id:
        stmt = stmt.where(Incident.camera_ids.any(camera_id))
    if event_type:
        stmt = stmt.where(Incident.event_type == event_type)
    rows = (await session.execute(stmt)).scalars().all()
    return IncidentsPage(items=[_summary(r) for r in rows])


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: str,
    request: Request,
    session: SessionDep,
    _user: Annotated[User, Depends(get_current_user)],
) -> IncidentDetail:
    row = await session.get(Incident, _uuid(incident_id, "incident"))
    if row is None:
        raise APIError("NOT_FOUND", "Incident not found.", status_code=status.HTTP_404_NOT_FOUND)
    evidence = row.evidence
    if evidence:
        s3 = request.app.state.s3
        evidence = {**evidence, "phases": [dict(p) for p in evidence.get("phases", [])]}
        for phase in evidence["phases"]:
            phase["views"] = [dict(v) for v in phase.get("views", [])]
            for view in phase["views"]:
                frames = []
                for f in view.get("frames", []):
                    uri = f.get("uri")
                    frames.append(
                        {
                            **{k: v for k, v in f.items() if k != "uri"},
                            "url": await s3.presign_get(uri) if uri else None,
                        }
                    )
                view["frames"] = frames
    return IncidentDetail(
        **_summary(row).model_dump(),
        report=row.report,
        evidence=evidence,
        provenance=row.provenance,
        notes=row.notes,
        failure=(row.provenance or {}).get("failure") if row.status == "failed" else None,
    )


@router.patch("/incidents/{incident_id}", response_model=IncidentSummary)
async def patch_incident(
    incident_id: str,
    body: IncidentPatch,
    session: SessionDep,
    _user: Annotated[User, Depends(_operator_up)],
) -> IncidentSummary:
    row = await session.get(Incident, _uuid(incident_id, "incident"))
    if row is None:
        raise APIError("NOT_FOUND", "Incident not found.", status_code=status.HTTP_404_NOT_FOUND)
    if body.status is not None:
        if row.status in ("generating", "failed"):
            raise APIError(
                "CONFLICT",
                "Only a finished report can be reviewed or closed.",
                status_code=status.HTTP_409_CONFLICT,
                details={"status": row.status},
            )
        row.status = body.status
    if body.notes is not None:
        row.notes = body.notes or None
    await session.flush()
    return _summary(row)


@router.get("/reasoning/jobs", response_model=list[JobOut])
async def list_jobs(
    session: SessionDep,
    _user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[JobOut]:
    rows = (
        (
            await session.execute(
                select(ReasoningJob).order_by(ReasoningJob.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [await _job_out(session, r) for r in rows]


@router.get("/reasoning/jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str, session: SessionDep, _user: Annotated[User, Depends(get_current_user)]
) -> JobOut:
    row = await session.get(ReasoningJob, _uuid(job_id, "job"))
    if row is None:
        raise APIError("NOT_FOUND", "Job not found.", status_code=status.HTTP_404_NOT_FOUND)
    return await _job_out(session, row)


async def _group_of(session, event_id: str) -> tuple[uuid.UUID | None, list[str]]:
    row = (
        await session.execute(
            text(
                "SELECT id, event_ids FROM events.correlation_groups WHERE status <> 'merged' "
                "AND :e = ANY(event_ids) ORDER BY created_at DESC LIMIT 1"
            ),
            {"e": event_id},
        )
    ).first()
    return (row[0], list(row[1])) if row else (None, [event_id])


@router.post(
    "/events/{event_id}/analyze", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED
)
async def analyze_event(
    event_id: str, session: SessionDep, user: Annotated[User, Depends(_operator_up)]
) -> JobOut:
    """Queue phase-aware reasoning for the correlation group holding this event (or the event
    alone if nothing linked to it). An analysis already queued or running for it is returned
    instead of a second one."""
    _uuid(event_id, "event")
    exists = (
        await session.execute(
            text("SELECT 1 FROM events.events WHERE id::text = :e AND status <> 'rejected'"),
            {"e": event_id},
        )
    ).first()
    if exists is None:
        raise APIError("NOT_FOUND", "Event not found.", status_code=status.HTTP_404_NOT_FOUND)
    group_id, event_ids = await _group_of(session, event_id)
    live = (
        (
            await session.execute(
                select(ReasoningJob)
                .where(
                    ReasoningJob.status.in_(("queued", "running")),
                    (ReasoningJob.group_id == group_id)
                    if group_id
                    else ReasoningJob.event_ids.any(event_id),
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if live is not None:
        return await _job_out(session, live)
    job = ReasoningJob(
        id=uuid.UUID(uuid7_str()),
        group_id=group_id,
        event_ids=event_ids,
        trigger="manual",
        requested_by=user.id,
    )
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return await _job_out(session, job)


@router.get("/events/{event_id}/reasoning", response_model=ReasoningState)
async def event_reasoning(
    event_id: str, session: SessionDep, _user: Annotated[User, Depends(get_current_user)]
) -> ReasoningState:
    _uuid(event_id, "event")
    group_id, _ids = await _group_of(session, event_id)
    cond = ReasoningJob.group_id == group_id if group_id else ReasoningJob.event_ids.any(event_id)
    job = (
        (
            await session.execute(
                select(ReasoningJob).where(cond).order_by(ReasoningJob.created_at.desc()).limit(1)
            )
        )
        .scalars()
        .first()
    )
    inc_cond = Incident.group_id == group_id if group_id else Incident.event_ids.any(event_id)
    incident = (
        (
            await session.execute(
                select(Incident)
                .where(inc_cond, Incident.status != "failed")
                .order_by(Incident.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return ReasoningState(
        job=await _job_out(session, job) if job else None,
        incident=_summary(incident) if incident else None,
    )


@router.get("/events/{event_id}/alert")
async def event_alert(
    event_id: str, session: SessionDep, _user: Annotated[User, Depends(get_current_user)]
) -> dict[str, str | None]:
    """The alert page that shows an event (the UI addresses events by alert id); null when the
    event raised none (below the alert threshold)."""
    _uuid(event_id, "event")
    row = (
        await session.execute(
            text("SELECT id::text FROM core.alerts WHERE event_id = :e"), {"e": event_id}
        )
    ).first()
    return {"alert_id": row[0] if row else None}


@router.get("/incidents/{incident_id}/similar")
async def similar_incidents(
    incident_id: str, request: Request, _user: Annotated[User, Depends(get_current_user)]
) -> dict[str, Any]:
    """Other incident reports like this one, from the retrieval service's text index."""
    import httpx

    _uuid(incident_id, "incident")
    settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(base_url=settings.retrieval_url, timeout=30.0) as client:
            response = await client.get(f"/incidents/{incident_id}/similar")
    except httpx.HTTPError as exc:
        raise APIError(
            "UPSTREAM_UNAVAILABLE",
            "Similar incidents are not available right now.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    if response.status_code == 404:
        raise APIError("NOT_FOUND", "Incident not found.", status_code=status.HTTP_404_NOT_FOUND)
    if response.status_code >= 400:
        raise APIError(
            "UPSTREAM_UNAVAILABLE",
            "Similar incidents are not available right now.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return response.json()
