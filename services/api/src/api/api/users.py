"""User management endpoints — admin only (FR-AUTH-04)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from vms_db.models import User, UserRole

from api.adapters.audit import write_audit_log
from api.adapters.users import (
    create_user,
    delete_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
)
from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import require_role
from api.schemas import UserCreateRequest, UserOut, UsersPage, UserUpdateRequest

router = APIRouter(prefix="/users", tags=["users"])

_admin_only = require_role(UserRole.ADMIN)


def _parse_user_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(
            "VALIDATION_ERROR", "Malformed user id.", status_code=status.HTTP_400_BAD_REQUEST
        ) from exc


@router.get("", response_model=UsersPage)
async def list_users_endpoint(
    session: SessionDep,
    _admin: Annotated[User, Depends(_admin_only)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> UsersPage:
    cursor_id = _parse_user_id(cursor) if cursor else None
    rows = await list_users(session, limit=limit + 1, cursor=cursor_id)
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = str(page[-1].id) if has_more and page else None
    return UsersPage(items=[UserOut.from_model(u) for u in page], next_cursor=next_cursor)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    body: UserCreateRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(_admin_only)],
) -> UserOut:
    if await get_user_by_email(session, body.email) is not None:
        raise APIError(
            "CONFLICT",
            "A user with this email already exists.",
            status_code=status.HTTP_409_CONFLICT,
        )
    try:
        user = await create_user(
            session,
            email=body.email,
            full_name=body.full_name,
            password=body.password,
            role=body.role,
        )
    except IntegrityError as exc:
        # The precheck above doesn't rule out a concurrent request creating
        # the same email between the check and this insert; the DB's own
        # unique constraint is the real guard — translate its failure into
        # the same 409 rather than letting it fall through to a generic 500.
        raise APIError(
            "CONFLICT",
            "A user with this email already exists.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc

    await write_audit_log(
        request.app.state.db_session_factory,
        user_id=admin.id,
        action="user.created",
        entity_type="user",
        entity_id=str(user.id),
        details={"email": user.email, "role": user.role.value},
    )
    return UserOut.from_model(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user_endpoint(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(_admin_only)],
) -> UserOut:
    target = await get_user_by_id(session, _parse_user_id(user_id))
    if target is None:
        raise APIError("NOT_FOUND", "User not found.", status_code=status.HTTP_404_NOT_FOUND)

    # Only fields update_user actually applies (it treats an explicit null
    # the same as "not sent" — see its docstring) — otherwise a client
    # sending "full_name": null would show up in the audit details as a
    # change that never happened.
    changes = {
        field: value
        for field, value in body.model_dump(exclude_unset=True).items()
        if value is not None
    }
    target = await update_user(
        session, target, full_name=body.full_name, role=body.role, is_active=body.is_active
    )
    await write_audit_log(
        request.app.state.db_session_factory,
        user_id=admin.id,
        action="user.updated",
        entity_type="user",
        entity_id=str(target.id),
        details=changes,
    )
    return UserOut.from_model(target)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_endpoint(
    user_id: str,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(_admin_only)],
) -> None:
    target = await get_user_by_id(session, _parse_user_id(user_id))
    if target is None:
        raise APIError("NOT_FOUND", "User not found.", status_code=status.HTTP_404_NOT_FOUND)

    await write_audit_log(
        request.app.state.db_session_factory,
        user_id=admin.id,
        action="user.deleted",
        entity_type="user",
        entity_id=str(target.id),
    )
    await delete_user(session, target)
