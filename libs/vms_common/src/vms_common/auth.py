"""Access-token JWT encode/decode (FR-AUTH-01) — pure, no I/O, shared by any
service that needs to issue or verify one (today: `services/api`; a future
service with its own HTTP surface would need the same logic, not a
reimplementation of it).

Password hashing and refresh-token generation stay service-local
(`services/api/src/api/domain/security.py`) — only `api` ever manages user
accounts, so there's no second consumer to share that with.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt


class InvalidTokenError(Exception):
    """Raised for any access token that fails to decode or doesn't validate."""


def encode_access_token(
    *, user_id: str, role: str, secret: str, algorithm: str, expires_minutes: int
) -> str:
    if not secret:
        # A blank HMAC key is accepted by PyJWT and forgeable by anyone — a
        # misconfigured deployment (VMS_JWT_SECRET unset) must fail loudly
        # here, not silently mint tokens anyone can replicate.
        raise InvalidTokenError("JWT secret is not configured (VMS_JWT_SECRET).")
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, *, secret: str, algorithm: str) -> dict[str, Any]:
    """Decode + validate an access token. Raises `InvalidTokenError` on any
    failure: bad signature, expired, wrong type, or an unconfigured secret.
    """
    if not secret:
        raise InvalidTokenError("JWT secret is not configured (VMS_JWT_SECRET).")
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != "access":
        raise InvalidTokenError("not an access token")
    return payload
