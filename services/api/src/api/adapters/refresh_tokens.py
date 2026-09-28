"""Refresh-token repository — SQLAlchemy queries against
`core.refresh_tokens`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import RefreshToken

from api.domain.security import generate_refresh_token, hash_refresh_token


async def issue_refresh_token(
    session: AsyncSession, *, user_id: uuid.UUID, expire_days: int
) -> tuple[str, RefreshToken]:
    """Create and persist a new refresh token row. Returns `(raw_token, row)`
    — the raw token is returned to the caller once and never stored.
    """
    raw_token = generate_refresh_token()
    row = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=expire_days),
    )
    session.add(row)
    await session.flush()
    return raw_token, row


async def get_valid_refresh_token(session: AsyncSession, raw_token: str) -> RefreshToken | None:
    """Look up a refresh token by its raw value. `None` if missing, revoked, or expired."""
    token_hash = hash_refresh_token(raw_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at < datetime.now(UTC):
        return None
    return row


async def revoke_refresh_token(
    session: AsyncSession, row: RefreshToken, *, replaced_by: RefreshToken | None = None
) -> None:
    row.revoked_at = datetime.now(UTC)
    if replaced_by is not None:
        row.replaced_by_id = replaced_by.id
    await session.flush()
