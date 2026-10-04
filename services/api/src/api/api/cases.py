"""Investigation cases (P6-J4, FR-INV-03; design §9): a named bundle of the things an operator
wants to keep together — events, incident reports, moments of footage, searches, notes. Cases are
shared by operators and admins (an investigation is handed over, not owned); viewers see none."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from vms_common.ids import uuid7_str
from vms_db.models import Case, CaseItem, User, UserRole

from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import require_role

router = APIRouter(prefix="/cases", tags=["cases"])

_operator_up = require_role(UserRole.ADMIN, UserRole.OPERATOR)
OperatorUp = Annotated[User, Depends(_operator_up)]

ItemKind = Literal["event", "incident", "footage", "search", "note"]


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class CasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["open", "closed"] | None = None


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ItemKind
    label: str = Field(min_length=1, max_length=500)
    ref: str | None = Field(default=None, max_length=500)
    camera_id: str | None = Field(default=None, max_length=100)
    ts_start: datetime | None = None
    ts_end: datetime | None = None
    note: str | None = Field(default=None, max_length=4000)


class ItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    ref: str | None
    label: str
    camera_id: str | None
    ts_start: datetime | None
    ts_end: datetime | None
    note: str | None
    created_at: datetime


class CaseOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str | None
    status: str
    item_count: int
    created_at: datetime
    updated_at: datetime


class CaseDetail(CaseOut):
    items: list[ItemOut]


def _item(row: CaseItem) -> ItemOut:
    return ItemOut(
        id=str(row.id),
        kind=row.kind,
        ref=row.ref,
        label=row.label,
        camera_id=row.camera_id,
        ts_start=row.ts_start,
        ts_end=row.ts_end,
        note=row.note,
        created_at=row.created_at,
    )


def _case(row: Case, count: int) -> CaseOut:
    return CaseOut(
        id=str(row.id),
        title=row.title,
        description=row.description,
        status=row.status,
        item_count=count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _id(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", f"Malformed {what} id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc


def _not_found() -> APIError:
    return APIError("NOT_FOUND", "Case not found.", status_code=status.HTTP_404_NOT_FOUND)


async def _count(session, case_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(CaseItem).where(CaseItem.case_id == case_id)
        )
    ).scalar_one()


@router.get("", response_model=list[CaseOut])
async def list_cases(session: SessionDep, _user: OperatorUp) -> list[CaseOut]:
    counts = select(CaseItem.case_id, func.count().label("n")).group_by(CaseItem.case_id).subquery()
    rows = (
        await session.execute(
            select(Case, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.case_id == Case.id)
            .order_by(Case.updated_at.desc())
            .limit(100)
        )
    ).all()
    return [_case(c, n) for c, n in rows]


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def create_case(body: CaseCreate, session: SessionDep, user: OperatorUp) -> CaseOut:
    row = Case(
        id=uuid.UUID(uuid7_str()), owner_id=user.id, title=body.title, description=body.description
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _case(row, 0)


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: str, session: SessionDep, _user: OperatorUp) -> CaseDetail:
    row = await session.get(Case, _id(case_id, "case"))
    if row is None:
        raise _not_found()
    items = (
        (
            await session.execute(
                select(CaseItem).where(CaseItem.case_id == row.id).order_by(CaseItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    return CaseDetail(**_case(row, len(items)).model_dump(), items=[_item(i) for i in items])


@router.patch("/{case_id}", response_model=CaseOut)
async def patch_case(
    case_id: str, body: CasePatch, session: SessionDep, _user: OperatorUp
) -> CaseOut:
    row = await session.get(Case, _id(case_id, "case"))
    if row is None:
        raise _not_found()
    for field in ("title", "description", "status"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    await session.flush()
    await session.refresh(row)
    return _case(row, await _count(session, row.id))


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(case_id: str, session: SessionDep, _user: OperatorUp) -> None:
    result = await session.execute(delete(Case).where(Case.id == _id(case_id, "case")))
    if result.rowcount == 0:
        raise _not_found()


@router.post("/{case_id}/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def add_item(
    case_id: str, body: ItemCreate, session: SessionDep, user: OperatorUp
) -> ItemOut:
    case = await session.get(Case, _id(case_id, "case"))
    if case is None:
        raise _not_found()
    if body.ts_start and body.ts_end and body.ts_end < body.ts_start:
        raise APIError(
            "VALIDATION_ERROR",
            "The end of the period cannot be before its start.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    row = CaseItem(
        id=uuid.UUID(uuid7_str()), case_id=case.id, added_by=user.id, **body.model_dump()
    )
    session.add(row)
    case.updated_at = func.now()
    await session.flush()
    await session.refresh(row)
    return _item(row)


@router.delete("/{case_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(case_id: str, item_id: str, session: SessionDep, _user: OperatorUp) -> None:
    result = await session.execute(
        delete(CaseItem).where(
            CaseItem.id == _id(item_id, "item"), CaseItem.case_id == _id(case_id, "case")
        )
    )
    if result.rowcount == 0:
        raise APIError("NOT_FOUND", "Item not found.", status_code=status.HTTP_404_NOT_FOUND)
