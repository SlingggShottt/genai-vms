"""Integration test: apply the full Alembic history to a throwaway Postgres
container and assert the `core` schema/tables/constraints land as designed
(P1-J1 AC: "Integration tests with testcontainers Postgres").

Run via `make test-int` (needs Docker).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer
from vms_db.models import AuditLog, Camera, RefreshToken, User, UserRole

pytestmark = pytest.mark.integration

VMS_DB_ROOT = Path(__file__).resolve().parents[2]


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


# NOTE: this test — and only this test — stays synchronous (no
# `@pytest.mark.asyncio`) on purpose: `command.upgrade` drives our async
# `migrations/env.py`, which calls `asyncio.run(...)` itself. Calling it from
# inside an already-running pytest-asyncio event loop would raise
# "asyncio.run() cannot be called from a running event loop".
def test_migration_0001_creates_core_schema_tables_and_constraints() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            alembic_cfg = Config(str(VMS_DB_ROOT / "alembic.ini"))
            command.upgrade(alembic_cfg, "head")

            info = asyncio.run(_inspect_core_schema(dsn))
            asyncio.run(_round_trip_insert(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)

    assert info["schemas"] >= {"core"}
    assert info["core_tables"] == {"users", "refresh_tokens", "cameras", "audit_log"}
    assert "user_role" in info["enum_types"]


async def _inspect_core_schema(dsn: str) -> dict:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:

            def _sync_inspect(sync_conn):
                inspector = inspect(sync_conn)
                enum_rows = sync_conn.exec_driver_sql(
                    "SELECT typname FROM pg_type WHERE typtype = 'e'"
                ).fetchall()
                return {
                    "schemas": set(inspector.get_schema_names()),
                    "core_tables": set(inspector.get_table_names(schema="core")),
                    "enum_types": {row[0] for row in enum_rows},
                }

            return await conn.run_sync(_sync_inspect)
    finally:
        await engine.dispose()


async def _round_trip_insert(dsn: str) -> None:
    """A migrated schema must accept the rows the ORM models will write."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(dsn)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            user = User(
                email="admin@genai-vms.local",
                full_name="Admin",
                password_hash="argon2id$stub",
                role=UserRole.ADMIN,
            )
            session.add(user)
            await session.flush()

            session.add(
                RefreshToken(
                    user_id=user.id,
                    token_hash=uuid.uuid4().hex,
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            )
            session.add(
                Camera(
                    code="cam01",
                    name="Front gate",
                    rtsp_url="rtsp://localhost/cam01",
                    site_id="rvce-campus",
                )
            )
            session.add(AuditLog(user_id=user.id, action="user.login"))
            await session.commit()

            refreshed = await session.get(User, user.id)
            assert refreshed is not None
            assert refreshed.role == UserRole.ADMIN
    finally:
        await engine.dispose()
