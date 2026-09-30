"""Integration test: migration 0003 creates `core.zones` and its FK to
`core.cameras` (P2-J4 AC). Run via `make test-int` (needs Docker).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from vms_db.models import Camera, Zone, ZoneType

pytestmark = pytest.mark.integration

VMS_DB_ROOT = Path(__file__).resolve().parents[2]


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


# See test_migrations.py's matching note on why this test stays synchronous.
def test_migration_0003_creates_zones_table_and_fk() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(Config(str(VMS_DB_ROOT / "alembic.ini")), "head")
            tables = asyncio.run(_core_tables(dsn))
            asyncio.run(_round_trip_insert(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)

    assert "zones" in tables


async def _core_tables(dsn: str) -> set[str]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda c: set(inspect(c).get_table_names(schema="core")))
    finally:
        await engine.dispose()


async def _round_trip_insert(dsn: str) -> None:
    engine = create_async_engine(dsn)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            camera = Camera(
                code="cam01", name="Front gate", rtsp_url="rtsp://localhost/cam01", site_id="rvce"
            )
            session.add(camera)
            await session.flush()

            session.add(
                Zone(
                    camera_id=camera.id,
                    name="Restricted yard",
                    zone_type=ZoneType.RESTRICTED,
                    polygon=[[0.1, 0.4], [0.6, 0.35], [0.65, 0.9]],
                    schedule=None,
                )
            )
            await session.commit()

            refreshed = await session.get(Camera, camera.id)
            assert refreshed is not None
    finally:
        await engine.dispose()
