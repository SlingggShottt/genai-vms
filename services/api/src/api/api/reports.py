"""Daily security reports (P6-J1/J5, design §9): list and read the reports the reasoning worker
wrote, and queue one for a date range. The api never builds a report; it inserts a `queued` row
(`reasoning.daily_reports`) and the worker aggregates the figures, writes the narrative and marks
it ready. Reading is open to every role, generating to operators and admins."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from vms_common.ids import uuid7_str
from vms_db.models import DailyReport, User, UserRole

from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.ratelimit import limit
from api.api.security import get_current_user, require_role

router = APIRouter(prefix="/reports/daily", tags=["reports"])

_operator_up = require_role(UserRole.ADMIN, UserRole.OPERATOR)
MAX_DAYS = 7
SITE_TZ = ZoneInfo("Asia/Kolkata")


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date
    date_to: date


class ReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    date_from: date
    date_to: date
    status: str
    narrative_source: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    has_pdf: bool = False


class PdfLink(BaseModel):
    """A short-lived link to the stored PDF (presigned per request, never stored)."""

    model_config = ConfigDict(extra="forbid")

    url: str
    expires_in: int = 900


class ReportDetail(ReportSummary):
    narrative: str | None
    facts: dict[str, Any] | None


def _summary(row: DailyReport) -> ReportSummary:
    return ReportSummary(
        id=str(row.id),
        date_from=row.date_from,
        date_to=row.date_to,
        status=row.status,
        narrative_source=row.narrative_source,
        error=row.error,
        created_at=row.created_at,
        finished_at=row.finished_at,
        has_pdf=bool(row.pdf_uri),
    )


@router.get("", response_model=list[ReportSummary])
async def list_reports(
    session: SessionDep,
    _user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[ReportSummary]:
    rows = (
        (
            await session.execute(
                select(DailyReport).order_by(DailyReport.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_summary(r) for r in rows]


@router.post(
    "",
    response_model=ReportSummary,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit("heavy"))],
)
async def request_report(
    body: ReportRequest, session: SessionDep, user: Annotated[User, Depends(_operator_up)]
) -> ReportSummary:
    today = datetime.now(SITE_TZ).date()
    if body.date_to < body.date_from:
        raise APIError(
            "VALIDATION_ERROR",
            "The end date cannot be before the start date.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if (body.date_to - body.date_from).days + 1 > MAX_DAYS:
        raise APIError(
            "VALIDATION_ERROR",
            f"A report covers at most {MAX_DAYS} days.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if body.date_to > today:
        raise APIError(
            "VALIDATION_ERROR",
            "A report cannot cover days that have not happened yet.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    row = DailyReport(
        id=uuid.UUID(uuid7_str()),
        date_from=body.date_from,
        date_to=body.date_to,
        requested_by=user.id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _summary(row)


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: str, session: SessionDep, _user: Annotated[User, Depends(get_current_user)]
) -> ReportDetail:
    try:
        rid = uuid.UUID(report_id)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", "Malformed report id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc
    row = await session.get(DailyReport, rid)
    if row is None:
        raise APIError("NOT_FOUND", "Report not found.", status_code=status.HTTP_404_NOT_FOUND)
    return ReportDetail(**_summary(row).model_dump(), narrative=row.narrative, facts=row.facts)


@router.get("/{report_id}/pdf", response_model=PdfLink)
async def get_report_pdf(
    report_id: str,
    request: Request,
    session: SessionDep,
    _user: Annotated[User, Depends(get_current_user)],
) -> PdfLink:
    try:
        rid = uuid.UUID(report_id)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", "Malformed report id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc
    row = await session.get(DailyReport, rid)
    if row is None:
        raise APIError("NOT_FOUND", "Report not found.", status_code=status.HTTP_404_NOT_FOUND)
    if not row.pdf_uri:
        raise APIError(
            "NOT_FOUND", "This report has no PDF yet.", status_code=status.HTTP_404_NOT_FOUND
        )
    return PdfLink(url=await request.app.state.s3.presign_get(row.pdf_uri))
