"""Integration test: migration 0005 creates `core.topology_edges` and the table itself
refuses malformed edges (P3-J1: "CRUD topology edges ... with validation" — the API
validates, the database is the backstop). Run via `make test-int` (needs Docker).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from vms_db.models import Camera, EdgeType, TopologyEdge

pytestmark = pytest.mark.integration

VMS_DB_ROOT = Path(__file__).resolve().parents[2]


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _config() -> Config:
    return Config(str(VMS_DB_ROOT / "alembic.ini"))


# See test_migrations.py's note on why migration tests stay synchronous.
def test_migration_0005_creates_the_table_and_it_enforces_its_rules() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(_config(), "head")
            tables = asyncio.run(_core_tables(dsn))
            asyncio.run(_exercise_constraints(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)

    assert "topology_edges" in tables


def test_migration_0005_downgrades_cleanly_and_can_be_reapplied() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(_config(), "head")
            command.downgrade(_config(), "0004")
            assert "topology_edges" not in asyncio.run(_core_tables(dsn))
            assert "edge_type" not in asyncio.run(_enum_types(dsn))  # no orphaned type
            command.upgrade(_config(), "head")  # and it can come back
            assert "topology_edges" in asyncio.run(_core_tables(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)


async def _core_tables(dsn: str) -> set[str]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda c: set(inspect(c).get_table_names(schema="core")))
    finally:
        await engine.dispose()


async def _enum_types(dsn: str) -> set[str]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE n.nspname = 'core' AND t.typtype = 'e'"
                )
            )
            return {r[0] for r in rows}
    finally:
        await engine.dispose()


def _transit(a: Camera, b: Camera, **kw: object) -> TopologyEdge:
    args: dict[str, object] = {
        "from_camera_id": a.id,
        "to_camera_id": b.id,
        "edge_type": EdgeType.TRANSIT,
        "min_s": 5.0,
        "max_s": 60.0,
        "bidirectional": False,
    }
    return TopologyEdge(**(args | kw))


def _overlap(a: Camera, b: Camera, **kw: object) -> TopologyEdge:
    args: dict[str, object] = {
        "from_camera_id": a.id,
        "to_camera_id": b.id,
        "edge_type": EdgeType.OVERLAP,
        "tolerance_s": 3.0,
        "bidirectional": True,
    }
    return TopologyEdge(**(args | kw))


async def _exercise_constraints(dsn: str) -> None:
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def rejected(edge: TopologyEdge) -> bool:
        """True if the database refuses this edge (each attempt gets its own transaction)."""
        async with factory() as session:
            session.add(edge)
            try:
                await session.commit()
            except IntegrityError:
                return True
            return False

    try:
        async with factory() as session:
            cams = [
                Camera(
                    code=f"cam0{i}", name=f"Camera {i}", rtsp_url=f"rtsp://x/cam0{i}", site_id="s"
                )
                for i in (1, 2, 3)
            ]
            session.add_all(cams)
            await session.commit()
        a, b, c = cams

        # valid edges go in
        async with factory() as session:
            session.add_all([_transit(a, b), _overlap(a, c)])
            await session.commit()

        assert await rejected(_transit(a, a)), "a camera must not link to itself"
        assert await rejected(_transit(a, b)), "same directed pair and type twice"
        assert await rejected(_overlap(c, a)), "overlap is symmetric: C-A duplicates A-C"
        assert await rejected(_transit(b, c, min_s=None)), "transit needs both bounds"
        assert await rejected(_transit(b, c, max_s=None)), "transit needs both bounds"
        assert await rejected(_transit(b, c, min_s=90.0, max_s=30.0)), "max below min"
        assert await rejected(_transit(b, c, min_s=-1.0)), "negative minimum"
        assert await rejected(_transit(b, c, tolerance_s=2.0)), "transit carries no tolerance"
        assert await rejected(_overlap(b, c, tolerance_s=None)), "overlap needs a tolerance"
        assert await rejected(_overlap(b, c, tolerance_s=-1.0)), "negative tolerance"
        assert await rejected(_overlap(b, c, min_s=1.0, max_s=2.0)), "overlap carries no window"
        assert await rejected(_overlap(b, c, bidirectional=False)), "overlap is always two-way"

        # but legitimate variations are fine
        async with factory() as session:
            session.add_all(
                [
                    _transit(b, a),  # the reverse *transit* is a different edge
                    _transit(a, c, min_s=0.0, max_s=0.0),  # a zero-width window is allowed
                    _transit(
                        a,
                        b,
                        edge_type=EdgeType.TRANSIT,
                        min_s=1.0,
                        max_s=2.0,
                        to_camera_id=c.id,
                        from_camera_id=b.id,
                    ),
                ]
            )
            await session.commit()

        # deleting a camera takes its edges with it
        async with factory() as session:
            await session.delete(await session.get(Camera, a.id))
            await session.commit()
            remaining = (
                await session.execute(text("SELECT count(*) FROM core.topology_edges"))
            ).scalar_one()
        assert remaining == 1  # only the b->c edge survives
    finally:
        await engine.dispose()
