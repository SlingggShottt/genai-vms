"""One migrated Postgres container per test session, shared by the events
integration tests (same shape as the indexer's). Run via `make test-int`
(needs Docker).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.community.postgres import PostgresContainer
from vms_common.config import DatabaseSettings
from vms_db.session import create_engine, create_session_factory

VMS_DB_ALEMBIC_INI = Path(__file__).resolve().parents[4] / "libs" / "vms_db" / "alembic.ini"


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture(scope="session")
def migrated_postgres_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        # command.upgrade drives the async env.py through its own asyncio.run(...).
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(Config(str(VMS_DB_ALEMBIC_INI)), "head")
        finally:
            os.environ.pop("VMS_DB_DSN", None)
        yield dsn


@pytest.fixture
async def session_factory(migrated_postgres_dsn: str) -> AsyncIterator[async_sessionmaker]:
    engine = create_engine(DatabaseSettings(dsn=migrated_postgres_dsn))
    factory = create_session_factory(engine)
    async with factory() as session:  # every test starts from empty candidates and events tables
        await session.execute(text("DELETE FROM events.events"))
        await session.execute(text("DELETE FROM events.candidates"))
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()
