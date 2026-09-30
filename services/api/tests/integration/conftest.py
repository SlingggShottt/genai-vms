"""Shared fixtures for api integration tests: one migrated Postgres
container per test session (fast), a fresh app/client per test (isolated
engine/connection pool), unique emails per test to avoid collisions in the
shared database. Run via `make test-int` (needs Docker).

Everything test files need is exposed as a fixture (not a module-level
import) so it works regardless of pytest's `--import-mode=importlib`
module-naming details for sibling test files.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from api.main import create_app
from api.settings import AdminSeedSettings, ApiSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import HttpWaitStrategy
from vms_common.config import DatabaseSettings, JWTSettings, RedisSettings, StorageSettings
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory

VMS_DB_ALEMBIC_INI = Path(__file__).resolve().parents[4] / "libs" / "vms_db" / "alembic.ini"

_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASSWORD = "admin-password-123"  # noqa: S105 — fixture value, not a real secret
_SERVICE_TOKEN = "test-service-token"  # noqa: S105 — fixture value, not a real secret
_JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"  # noqa: S105 — fixture value


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture(scope="session")
def migrated_postgres_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        # alembic's env.py reads VMS_DB_DSN (not the ini file) — see
        # libs/vms_db/migrations/env.py. This upgrade runs once, synchronously,
        # outside any pytest-asyncio loop (same constraint as
        # libs/vms_db/tests/integration/test_migrations.py).
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(Config(str(VMS_DB_ALEMBIC_INI)), "head")
        finally:
            os.environ.pop("VMS_DB_DSN", None)
        yield dsn


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as redis:
        yield f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"


@pytest.fixture
async def redis_client(redis_url: str) -> Iterator[Redis]:
    """A client tests can use to write heartbeats directly, separate from
    the app's own client (`app.state.redis_client`) — same container.
    """
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture(scope="session")
def s3_mock_container() -> Iterator[DockerContainer]:
    """An S3-compatible test double, not real MinIO: both `minio/minio` on
    Docker Hub and `quay.io/minio/minio` (what
    deploy/compose/docker-compose.yml's real `minio` service pins) now
    return 401/404 on every tag when pulled from this environment — MinIO
    tightened anonymous-pull access at some point after that pin was
    written. `adobe/s3mock` is a plain S3-API test double (no real
    object-storage semantics beyond what boto3 needs here), still openly
    pullable, and sufficient for what these tests actually exercise
    (put/get/presign against `S3Client`, the same boto3 wrapper the app
    uses). Worth re-pointing at real MinIO once its access story is sorted.
    """
    container = (
        DockerContainer("adobe/s3mock:latest")
        .with_env("initialBuckets", "vms-segments,vms-twins")
        .with_exposed_ports(9090)
        .waiting_for(HttpWaitStrategy(9090, "/favicon.ico").for_status_code(200))
    )
    with container as c:
        yield c


@pytest.fixture
def storage_settings(s3_mock_container: DockerContainer) -> StorageSettings:
    endpoint = f"http://{s3_mock_container.get_container_host_ip()}:{s3_mock_container.get_exposed_port(9090)}"
    return StorageSettings(endpoint_url=endpoint, access_key="test", secret_key="test")


@pytest.fixture
async def s3_client(storage_settings: StorageSettings) -> Iterator[S3Client]:
    """A client tests use to seed twin JSON / segment objects directly —
    same MinIO the app itself talks to (`app.state.s3`, same `storage_settings`).
    """
    client = S3Client(
        endpoint_url=storage_settings.endpoint_url,
        access_key=storage_settings.access_key,
        secret_key=storage_settings.secret_key,
    )
    for bucket in ("vms-segments", "vms-twins"):
        await client.ensure_bucket(bucket)
    yield client


@pytest.fixture
async def db_session_factory(migrated_postgres_dsn: str) -> Iterator[async_sessionmaker]:
    """Writes directly into `media.segments`/`vision.minute_counts` —
    there's no API endpoint for those, they're the indexer's job (P2-J1);
    tests seed the rows the recordings endpoints are meant to read.
    """
    engine = create_engine(DatabaseSettings(dsn=migrated_postgres_dsn))
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def admin_email() -> str:
    return _ADMIN_EMAIL


@pytest.fixture
def admin_password() -> str:
    return _ADMIN_PASSWORD


@pytest.fixture
def service_token() -> str:
    return _SERVICE_TOKEN


@pytest.fixture
def jwt_secret() -> str:
    return _JWT_SECRET


@pytest.fixture
def api_settings(
    migrated_postgres_dsn: str, redis_url: str, storage_settings: StorageSettings
) -> ApiSettings:
    return ApiSettings(
        db=DatabaseSettings(dsn=migrated_postgres_dsn),
        jwt=JWTSettings(secret=_JWT_SECRET),
        admin=AdminSeedSettings(email=_ADMIN_EMAIL, password=_ADMIN_PASSWORD),
        service_token=_SERVICE_TOKEN,
        redis=RedisSettings(url=redis_url),
        storage=storage_settings,
    )


@pytest.fixture
def app(api_settings: ApiSettings) -> FastAPI:
    return create_app(api_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_access_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def auth_headers() -> Callable[[str], dict[str, str]]:
    def _make(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _make
