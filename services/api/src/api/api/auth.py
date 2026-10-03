"""Auth endpoints: login, refresh, logout, me (FR-AUTH-01)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from vms_common.auth import encode_access_token
from vms_db.models import RefreshToken, User

from api.adapters.audit import write_audit_log
from api.adapters.refresh_tokens import (
    get_valid_refresh_token,
    issue_refresh_token,
    revoke_refresh_token,
)
from api.adapters.users import get_user_by_email, get_user_by_id
from api.api.deps import SessionDep
from api.api.errors import APIError
from api.api.security import get_current_user
from api.domain.security import verify_password
from api.schemas import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue_token_pair(
    request: Request, session: AsyncSession, user: User
) -> tuple[TokenResponse, RefreshToken]:
    settings = request.app.state.settings
    access_token = encode_access_token(
        user_id=str(user.id),
        role=user.role.value,
        secret=settings.jwt.secret,
        algorithm=settings.jwt.algorithm,
        expires_minutes=settings.jwt.access_token_expire_minutes,
    )
    raw_refresh_token, row = await issue_refresh_token(
        session, user_id=user.id, expire_days=settings.jwt.refresh_token_expire_days
    )
    response = TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh_token,
        expires_in=settings.jwt.access_token_expire_minutes * 60,
    )
    return response, row


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: SessionDep,
) -> TokenResponse:
    user = await get_user_by_email(session, body.email)
    # Argon2id is deliberately slow (CPU-bound) — never call it directly
    # inside async def (style_guide.md §A.1); offload to a thread.
    password_ok = user is not None and await asyncio.to_thread(
        verify_password, body.password, user.password_hash
    )
    if user is None or not user.is_active or not password_ok:
        await write_audit_log(
            request.app.state.db_session_factory,
            user_id=user.id if user else None,
            action="user.login_failed",
            entity_type="user",
            entity_id=str(user.id) if user else None,
            details={"email": body.email},
        )
        raise APIError(
            "INVALID_CREDENTIALS",
            "Invalid email or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    tokens, _ = await _issue_token_pair(request, session, user)
    await write_audit_log(
        request.app.state.db_session_factory,
        user_id=user.id,
        action="user.login",
        entity_type="user",
        entity_id=str(user.id),
    )
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    session: SessionDep,
) -> TokenResponse:
    existing = await get_valid_refresh_token(session, body.refresh_token)
    if existing is None:
        raise APIError(
            "INVALID_TOKEN",
            "Refresh token is invalid, expired, or already used.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user = await get_user_by_id(session, existing.user_id)
    if user is None or not user.is_active:
        raise APIError(
            "UNAUTHENTICATED",
            "User not found or inactive.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    tokens, new_row = await _issue_token_pair(request, session, user)
    await revoke_refresh_token(session, existing, replaced_by=new_row)
    await write_audit_log(
        request.app.state.db_session_factory,
        user_id=user.id,
        action="user.token_refreshed",
        entity_type="user",
        entity_id=str(user.id),
    )
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: SessionDep,
) -> None:
    # Only revoke if the token belongs to the caller — an unrelated or
    # already-invalid token still 204s (idempotent "you're logged out"),
    # it just revokes nothing.
    existing = await get_valid_refresh_token(session, body.refresh_token)
    if existing is not None and existing.user_id == current_user.id:
        await revoke_refresh_token(session, existing)
    await write_audit_log(
        request.app.state.db_session_factory,
        user_id=current_user.id,
        action="user.logout",
        entity_type="user",
        entity_id=str(current_user.id),
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return UserOut.from_model(current_user)
