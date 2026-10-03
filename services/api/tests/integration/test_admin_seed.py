"""Seeding the admin account when several api replicas start together (P3-J3: "works with 2 API
replicas" — found when the second of two replicas crashed at start-up on an empty database).
Run via `make test-int`."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from api.adapters.users import seed_admin_user
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_db.models import User, UserRole
from vms_db.session import session_scope

pytestmark = pytest.mark.integration

PASSWORD = "seed-password-123"  # noqa: S105 - fixture value


@pytest.fixture
async def made_emails(db_session_factory: async_sessionmaker):
    """Emails a test creates. They are deleted afterwards: the database is shared by the whole
    session, and other tests (test_auth's "exactly one admin") count the admins in it."""
    emails: list[str] = []
    yield emails
    async with session_scope(db_session_factory) as session:
        await session.execute(delete(User).where(User.email.in_(emails)))


async def _seed(factory: async_sessionmaker, email: str) -> None:
    async with session_scope(factory) as session:
        await seed_admin_user(session, email=email, password=PASSWORD)


async def _count(factory: async_sessionmaker, email: str) -> int:
    async with factory() as session:
        return await session.scalar(
            select(func.count()).select_from(User).where(User.email == email)
        )


async def test_replicas_seeding_the_same_admin_at_once_all_succeed_with_one_account(
    db_session_factory: async_sessionmaker, made_emails: list[str]
) -> None:
    email = f"seed-{uuid.uuid4().hex[:8]}@example.com"
    made_emails.append(email)

    await asyncio.gather(*(_seed(db_session_factory, email) for _ in range(6)))  # none may raise

    assert await _count(db_session_factory, email) == 1
    async with db_session_factory() as session:
        admin = (await session.execute(select(User).where(User.email == email))).scalar_one()
    assert admin.role == UserRole.ADMIN and admin.is_active


async def test_seeding_twice_in_a_row_is_still_a_no_op(
    db_session_factory: async_sessionmaker, made_emails: list[str]
) -> None:
    email = f"seed-{uuid.uuid4().hex[:8]}@example.com"
    made_emails.append(email)
    await _seed(db_session_factory, email)
    await _seed(db_session_factory, email)
    assert await _count(db_session_factory, email) == 1


async def test_the_losing_replicas_other_work_in_its_transaction_survives(
    db_session_factory: async_sessionmaker, made_emails: list[str]
) -> None:
    """The savepoint: losing the race must not roll back what else the caller did."""
    email = f"seed-{uuid.uuid4().hex[:8]}@example.com"
    other = f"other-{uuid.uuid4().hex[:8]}@example.com"
    made_emails.extend([email, other])
    await _seed(db_session_factory, email)  # the winner

    async with session_scope(db_session_factory) as session:
        session.add(User(email=other, full_name="Other", password_hash="x", role=UserRole.VIEWER))
        await session.flush()
        # `get_user_by_email` would see the winner and return early; force the insert path.
        from api.adapters import users as users_module  # noqa: PLC0415

        original = users_module.get_user_by_email

        async def blind(*_a: object, **_k: object) -> None:
            return None

        users_module.get_user_by_email = blind  # type: ignore[assignment]
        try:
            await seed_admin_user(session, email=email, password=PASSWORD)
        finally:
            users_module.get_user_by_email = original  # type: ignore[assignment]

    assert await _count(db_session_factory, other) == 1  # committed despite the lost race
    assert await _count(db_session_factory, email) == 1
