"""One migrated Postgres container per test session, shared by indexer's
integration tests. Run via `make test-int` (needs Docker).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.qdrant import QdrantContainer
from vms_common.config import DatabaseSettings
from vms_common.qdrant.collections import ensure_collections
from vms_db.session import create_engine, create_session_factory

VMS_DB_ALEMBIC_INI = Path(__file__).resolve().parents[4] / "libs" / "vms_db" / "alembic.ini"


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture(scope="session")
def migrated_postgres_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        # Same constraint as libs/vms_db/tests/integration/test_migrations.py:
        # command.upgrade drives async env.py via its own asyncio.run(...).
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(Config(str(VMS_DB_ALEMBIC_INI)), "head")
        finally:
            os.environ.pop("VMS_DB_DSN", None)
        yield dsn


@pytest.fixture
async def session_factory(migrated_postgres_dsn: str) -> Iterator[async_sessionmaker]:
    engine = create_engine(DatabaseSettings(dsn=migrated_postgres_dsn))
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def qdrant_container() -> Iterator[QdrantContainer]:
    # Pinned to match deploy/compose/docker-compose.yml's qdrant service
    # (not QdrantContainer's own newer default) so this test actually
    # exercises the server version the app talks to in practice.
    with QdrantContainer(image="qdrant/qdrant:v1.11.5") as qdrant:
        yield qdrant


@pytest.fixture
async def qdrant_client(qdrant_container: QdrantContainer) -> Iterator[AsyncQdrantClient]:
    """One client per test, but the collections are created once (session
    scope) and reused — same rationale as `migrated_postgres_dsn`: tests use
    distinct camera_id/segment_id values to avoid colliding in shared state.
    """
    # QdrantContainer's own rest/grpc ports (6333/6334, its defaults — see
    # testcontainers.community.qdrant.QdrantContainer.__init__ and
    # .get_client(), which uses the same pair with no public accessor).
    client = AsyncQdrantClient(
        host=qdrant_container.get_container_host_ip(),
        port=qdrant_container.get_exposed_port(6333),
        grpc_port=qdrant_container.get_exposed_port(6334),
        https=False,
    )
    try:
        await ensure_collections(client)
        yield client
    finally:
        await client.close()
