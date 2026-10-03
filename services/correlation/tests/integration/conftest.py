"""Integration fixtures for correlation: one migrated Postgres container per session, a
consumer + sweeper wired to it with a controllable clock and a recording publisher. Run via
`make test-int` (needs Docker).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from alembic import command
from alembic.config import Config
from correlation.domain.config import CorrelationConfig
from correlation.domain.topology import Topology
from correlation.sweeper import Sweeper
from correlation.worker import CorrelationConsumer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.community.postgres import PostgresContainer
from vms_common.config import DatabaseSettings
from vms_common.contracts.correlation import CorrelationV1
from vms_common.contracts.event import EventV1
from vms_common.contracts.topology import TopologyInternalResponse
from vms_db.session import create_engine, create_session_factory

REPO = Path(__file__).resolve().parents[4]
VMS_DB_ALEMBIC_INI = REPO / "libs" / "vms_db" / "alembic.ini"
FIXTURES = REPO / "libs" / "vms_common" / "src" / "vms_common" / "fixtures"
ORIGIN = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)  # the fixtures' scenario starts here


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture(scope="session")
def migrated_postgres_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
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
    async with factory() as session:  # every test starts from empty tables
        await session.execute(text("DELETE FROM events.correlation_groups"))
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


class Clock:
    """A wall clock the test moves by hand (seconds after the fixtures' 10:15:00Z origin)."""

    def __init__(self) -> None:
        self.now = ORIGIN

    def __call__(self) -> datetime:
        return self.now

    def set(self, seconds: float) -> None:
        self.now = ORIGIN + timedelta(seconds=seconds)


@dataclass
class RecordingPublisher:
    messages: list[CorrelationV1] = field(default_factory=list)
    fail_next: int = 0  # the next N publishes raise (a Kafka outage)
    published: asyncio.Event = field(default_factory=asyncio.Event)  # set on every success

    async def publish(self, message: CorrelationV1) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("kafka is down")
        self.messages.append(message)
        self.published.set()

    def of(self, group_id: str) -> list[CorrelationV1]:
        return [m for m in self.messages if m.group_id == group_id]


@dataclass
class Rig:
    consumer: CorrelationConsumer
    sweeper: Sweeper
    publisher: RecordingPublisher
    clock: Clock
    session_factory: async_sessionmaker
    config: CorrelationConfig
    topology: Topology
    lock: asyncio.Lock

    async def deliver(self, event: EventV1) -> None:
        await self.consumer.handle(event, None)  # type: ignore[arg-type]

    def rebuild(self) -> Rig:
        """A fresh consumer and sweeper over the same database — what a restart looks like."""
        return make_rig(
            self.session_factory,
            self.config,
            self.topology,
            publisher=self.publisher,
            clock=self.clock,
        )


def make_rig(
    session_factory: async_sessionmaker,
    config: CorrelationConfig,
    topology: Topology,
    *,
    publisher: RecordingPublisher | None = None,
    clock: Clock | None = None,
) -> Rig:
    publisher = publisher or RecordingPublisher()
    clock = clock or Clock()
    lock = asyncio.Lock()
    consumer = CorrelationConsumer(
        topic="vms.events.v1",
        group_id="correlation-test",
        bootstrap_servers="unused:9092",
        model=EventV1,
        dlq_topic="vms.dlq.v1",
        session_factory=session_factory,
        get_topology=lambda: topology,
        config=config,
        lock=lock,
        clock=clock,
    )
    sweeper = Sweeper(
        session_factory=session_factory,
        publisher=publisher,
        get_topology=lambda: topology,
        config=config,
        lock=lock,
        interval_s=0.01,
        clock=clock,
    )
    return Rig(consumer, sweeper, publisher, clock, session_factory, config, topology, lock)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def shipped_config() -> CorrelationConfig:
    return CorrelationConfig.model_validate(
        yaml.safe_load((REPO / "config" / "correlation.yaml").read_text())
    )


@pytest.fixture
def fixture_topology() -> Topology:
    raw = json.loads((FIXTURES / "topology_internal.json").read_text())
    return Topology(TopologyInternalResponse.model_validate(raw).edges)


@pytest.fixture
def rig(session_factory, shipped_config, fixture_topology) -> Rig:
    return make_rig(session_factory, shipped_config, fixture_topology)


@pytest.fixture
def rig_for(session_factory, shipped_config) -> Callable[[Topology], Rig]:
    """A rig over a camera graph of the test's own."""

    def build(topology: Topology) -> Rig:
        return make_rig(session_factory, shipped_config, topology)

    return build


EventMaker = Callable[..., EventV1]


@pytest.fixture
def event() -> EventMaker:
    """`event("intrusion")` / `event("running_skipped", site_id="north")` — a fixture event.v1."""

    def make(name: str, **changes: object) -> EventV1:
        raw = json.loads((FIXTURES / f"event_v1_{name}.json").read_text())
        return EventV1.model_validate(raw | changes)

    return make
