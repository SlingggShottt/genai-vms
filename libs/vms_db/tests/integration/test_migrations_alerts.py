"""Integration test: migration 0007 creates `core.alerts` and the table refuses an impossible
lifecycle (P3-J3: ack/resolve with notes). Run via `make test-int` (needs Docker)."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from vms_db.models import Alert, User, UserRole

pytestmark = pytest.mark.integration

VMS_DB_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _config() -> Config:
    return Config(str(VMS_DB_ROOT / "alembic.ini"))


def test_migration_0007_creates_alerts_and_enforces_the_lifecycle() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(_config(), "head")
            assert "alerts" in asyncio.run(_core_tables(dsn))
            asyncio.run(_exercise(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)


def test_migration_0007_downgrades_cleanly_and_can_be_reapplied() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(_config(), "head")
            command.downgrade(_config(), "0006")
            assert "alerts" not in asyncio.run(_core_tables(dsn))
            command.upgrade(_config(), "head")
            assert "alerts" in asyncio.run(_core_tables(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)


async def _core_tables(dsn: str) -> set[str]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda c: set(inspect(c).get_table_names(schema="core")))
    finally:
        await engine.dispose()


def _alert(**kw: object) -> Alert:
    args: dict[str, object] = {
        "event_id": str(uuid.uuid4()),
        "site_id": "site",
        "camera_id": "cam02",
        "event_type": "intrusion",
        "severity": "high",
        "rule_id": "intrusion.after_hours",
        "title": "Intrusion on cam02",
        "verification_status": "verified",
        "start_ts": NOW,
        "end_ts": NOW + timedelta(seconds=20),
        "status": "open",
    }
    return Alert(**(args | kw))


async def _exercise(dsn: str) -> None:
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def rejected(row: object) -> bool:
        """True if the database refuses this row (each attempt gets its own transaction)."""
        async with factory() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                return True
            return False

    try:
        async with factory() as session:
            user = User(
                email="op@example.com", full_name="Op", password_hash="x", role=UserRole.OPERATOR
            )
            session.add(user)
            await session.commit()

        later = NOW + timedelta(minutes=1)
        # the lifecycle states that are allowed
        assert not await rejected(_alert()), "a plain open alert"
        assert not await rejected(
            _alert(status="acknowledged", acknowledged_at=later, acknowledged_by=user.id)
        )
        assert not await rejected(_alert(status="resolved", resolved_at=later)), "resolved at once"
        assert not await rejected(
            _alert(status="resolved", acknowledged_at=later, resolved_at=later)
        ), "acknowledged, then resolved"

        # one alert per event
        event = str(uuid.uuid4())
        assert not await rejected(_alert(event_id=event))
        assert await rejected(_alert(event_id=event)), "a second alert for the same event"

        # and the states that are not
        assert await rejected(_alert(status="paused")), "unknown status"
        assert await rejected(_alert(severity="meh")), "unknown severity"
        assert await rejected(_alert(status="acknowledged")), "acknowledged without a timestamp"
        assert await rejected(_alert(status="open", acknowledged_at=later)), "open but acknowledged"
        assert await rejected(_alert(status="open", resolved_at=later)), "open but resolved"
        assert await rejected(_alert(status="resolved")), "resolved without a timestamp"
        assert await rejected(
            _alert(status="acknowledged", acknowledged_at=later, resolved_at=later)
        ), "acknowledged but also resolved"

        # a user who leaves keeps their handled alerts as history
        handled = _alert(status="acknowledged", acknowledged_at=later, acknowledged_by=user.id)
        async with factory() as session:
            session.add(handled)
            await session.commit()
            await session.execute(text("DELETE FROM core.users WHERE id = :u"), {"u": user.id})
            await session.commit()
        async with factory() as fresh:  # a new session: the first still holds the old values
            kept = await fresh.get(Alert, handled.id)
            assert kept is not None and kept.acknowledged_by is None
            assert kept.status == "acknowledged"
    finally:
        await engine.dispose()
