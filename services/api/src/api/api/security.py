"""Auth dependencies: current-user extraction, role enforcement
(`require_role`), and the service-token check for `/internal/*`
(design_architecture.md §15, style_guide.md §A.5 status codes).
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from vms_common.auth import InvalidTokenError, decode_access_token
from vms_db.models import User, UserRole

from api.adapters.users import get_user_by_id
from api.api.deps import SessionDep
from api.api.errors import APIError

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
) -> User:
    """Decode the access token and re-load the user from the DB on every
    call — a JWT claim can't reflect a role change or deactivation
    (FR-AUTH-04) that happened after it was issued, so we don't trust it
    for authorization, only for identifying who to look up. The returned
    `User` stays attached to this request's session (`expire_on_commit=
    False`), so callers can read its attributes for the rest of the request.
    """
    if credentials is None:
        raise APIError(
            "UNAUTHENTICATED", "Missing bearer token.", status_code=status.HTTP_401_UNAUTHORIZED
        )

    settings = request.app.state.settings
    try:
        payload = decode_access_token(
            credentials.credentials, secret=settings.jwt.secret, algorithm=settings.jwt.algorithm
        )
    except InvalidTokenError as exc:
        raise APIError(
            "UNAUTHENTICATED",
            "Invalid or expired token.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise APIError(
            "UNAUTHENTICATED", "Invalid or expired token.", status_code=status.HTTP_401_UNAUTHORIZED
        ) from exc

    user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise APIError(
            "UNAUTHENTICATED",
            "User not found or inactive.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    return user


def require_role(*allowed: UserRole) -> Callable[..., Coroutine[None, None, User]]:
    """`Depends(require_role(UserRole.ADMIN))` — 403s anyone not in `allowed`."""

    async def _check(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in allowed:
            raise APIError(
                "FORBIDDEN",
                "You do not have permission to perform this action.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return current_user

    return _check


async def require_service_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """`/internal/*` guard — a static shared secret, not a JWT. An unset
    `service_token` rejects every request rather than accepting anything
    (an empty expected value must never equal an empty presented one).
    """
    settings = request.app.state.settings
    expected = settings.service_token
    presented = credentials.credentials if credentials else ""
    if not expected or not presented or not hmac.compare_digest(presented, expected):
        raise APIError(
            "UNAUTHENTICATED", "Invalid service token.", status_code=status.HTTP_401_UNAUTHORIZED
        )
