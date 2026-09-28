"""Integration test: `/ready` reports the database as up against a real,
migrated Postgres container (P1-J1 AC). Run via `make test-int`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from api.main import create_app
from api.settings import ApiSettings
from fastapi.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer
from vms_common.config import DatabaseSettings

pytestmark = pytest.mark.integration

VMS_DB_ALEMBIC_INI = Path(__file__).resolve().parents[4] / "libs" / "vms_db" / "alembic.ini"


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


# Synchronous on purpose — see libs/vms_db/tests/integration/test_migrations.py
# for why `command.upgrade` can't run inside a pytest-asyncio event loop.
def test_ready_reports_database_up_against_a_migrated_postgres() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(Config(str(VMS_DB_ALEMBIC_INI)), "head")

            settings = ApiSettings(db=DatabaseSettings(dsn=dsn))
            with TestClient(create_app(settings)) as client:
                response = client.get("/ready")
        finally:
            os.environ.pop("VMS_DB_DSN", None)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "up"}}
