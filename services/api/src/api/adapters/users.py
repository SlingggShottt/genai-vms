"""User repository — SQLAlchemy queries against `core.users`. No business
rules here (uniqueness, permission checks); that's the router's job.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.models import User, UserRole

from api.domain.security import hash_password


def _normalize_email(email: str) -> str:
    """Emails are looked up case-insensitively (nothing else in this module
    normalizes on write either, so this is the single place both sides agree).
    """
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == _normalize_email(email)))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def list_users(session: AsyncSession, *, limit: int, cursor: uuid.UUID | None) -> list[User]:
    """Cursor pagination on `id`, newest first: uuid7 is time-ordered, so
    `ORDER BY id DESC` with `id < cursor` for the next page surfaces
    recently created rows by default — an ascending, no-cursor first page
    would show the same oldest N forever once the table passes `limit` rows.
    """
    stmt = select(User).order_by(User.id.desc()).limit(limit)
    if cursor is not None:
        stmt = stmt.where(User.id < cursor)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_user(
    session: AsyncSession, *, email: str, full_name: str, password: str, role: UserRole
) -> User:
    # Argon2id is deliberately slow (CPU-bound) — never call it directly
    # inside async def (style_guide.md §A.1); offload to a thread.
    password_hash = await asyncio.to_thread(hash_password, password)
    user = User(
        email=_normalize_email(email), full_name=full_name, password_hash=password_hash, role=role
    )
    session.add(user)
    await session.flush()  # populates server-generated defaults (id, created_at) for the caller
    return user


async def update_user(
    session: AsyncSession,
    user: User,
    *,
    full_name: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
) -> User:
    if full_name is not None:
        user.full_name = full_name
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    # No flush: nothing reads back a server-generated value here — the
    # request-scoped session's commit (api.api.deps.get_session) persists it.
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)


async def seed_admin_user(session: AsyncSession, *, email: str, password: str) -> None:
    """Create the admin account on first start if it doesn't exist yet
    (P1-J2 AC). No-op when `password` is empty (nothing to seed with) or an
    account with this email already exists — including one created a moment
    ago by another replica starting at the same time. Caller owns the
    transaction (e.g. `vms_db.session.session_scope` from the app lifespan).
    """
    if not password:
        return
    if await get_user_by_email(session, email) is not None:
        return
    try:
        # A savepoint, so losing a race rolls back only this insert, not the caller's transaction.
        async with session.begin_nested():
            await create_user(
                session,
                email=email,
                full_name="Administrator",
                password=password,
                role=UserRole.ADMIN,
            )
    except IntegrityError:
        # Another replica starting at the same moment seeded the account between our check and
        # our insert (the unique email decided). That is the outcome we wanted.
        return
