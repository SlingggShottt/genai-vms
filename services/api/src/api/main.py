"""Entrypoint for the api service: FastAPI app factory + uvicorn runner.

Implementation grows with each story — see docs/backlog.md and
docs/design_architecture.md §9 for the full endpoint surface this lands.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.logging import configure_logging, get_logger
from vms_common.redis import get_redis_client
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory, session_scope

from api.adapters.users import seed_admin_user
from api.api.alerts import router as alerts_router
from api.api.assistant import router as assistant_router
from api.api.auth import router as auth_router
from api.api.cameras import router as cameras_router
from api.api.cases import router as cases_router
from api.api.correlations import router as correlations_router
from api.api.errors import register_exception_handlers
from api.api.health import router as health_router
from api.api.incidents import router as incidents_router
from api.api.internal import router as internal_router
from api.api.middleware import RequestIDMiddleware
from api.api.recordings import router as recordings_router
from api.api.reports import router as reports_router
from api.api.search import router as search_router
from api.api.timeline import router as timeline_router
from api.api.topology import router as topology_router
from api.api.tracks import router as tracks_router
from api.api.twin import router as twin_router
from api.api.users import router as users_router
from api.api.ws import router as ws_router
from api.api.zones import router as zones_router
from api.consumers.alerts import AlertEventConsumer, AlertGroupConsumer
from api.consumers.supervisor import supervise
from api.notifiers import NotificationDispatcher, build_dispatcher
from api.realtime.hub import ConnectionHub
from api.realtime.relay import RedisRelay
from api.settings import ApiSettings

log = get_logger(__name__)


SHUTDOWN_GRACE_S = 5.0


async def _stop_tasks(tasks: list[asyncio.Task], *, grace_s: float = SHUTDOWN_GRACE_S) -> None:
    """Cancel background tasks and wait for them — but only `grace_s`. A task that does not
    end (a library swallowing the cancellation) is reported and abandoned: the process is
    shutting down, and a hung shutdown is worse than an unfinished task."""
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    _done, pending = await asyncio.wait(tasks, timeout=grace_s)
    for task in pending:
        frames = [
            f"{f.f_code.co_filename.rsplit('/', 1)[-1]}:{f.f_lineno}" for f in task.get_stack()
        ]
        log.error("background_task_did_not_stop", task=task.get_name(), stack=frames)


def _start_alert_consumers(
    settings: ApiSettings,
    session_factory: async_sessionmaker[AsyncSession],
    relay: RedisRelay,
    dispatcher: NotificationDispatcher,
) -> list[asyncio.Task]:
    """The two Kafka consumers behind alerts, each supervised so a broker blip (or Kafka not
    being up yet) never takes alerting down for the rest of the process's life."""
    servers = settings.kafka.bootstrap_servers
    a = settings.alerts
    return [
        asyncio.create_task(
            supervise(
                "alerts-events",
                lambda: AlertEventConsumer(
                    topic=a.events_topic,
                    group_id=a.events_group,
                    bootstrap_servers=servers,
                    dlq_topic=settings.kafka.dlq_topic,
                    session_factory=session_factory,
                    dispatcher=dispatcher,
                    min_severity=a.min_severity,
                    notify_max_age_s=a.notify_max_age_seconds,
                ),
            ),
            name="alerts-events-consumer",
        ),
        asyncio.create_task(
            supervise(
                "alerts-correlations",
                lambda: AlertGroupConsumer(
                    topic=a.correlations_topic,
                    group_id=a.correlations_group,
                    bootstrap_servers=servers,
                    dlq_topic=settings.kafka.dlq_topic,
                    session_factory=session_factory,
                    relay=relay,
                ),
            ),
            name="alerts-correlations-consumer",
        ),
    ]


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Configured on startup, not at create_app()/import time: create_app()
        # can be called more than once (e.g. once per test), and importing
        # api.main (module-level `app = create_app()` below) shouldn't mutate
        # process-global logging state as a side effect (style_guide.md §A.1;
        # mirrors ingestion/main.py's `_amain()`).
        configure_logging(level=settings.log_level)
        engine = create_engine(settings.db)
        app.state.db_engine = engine
        session_factory = create_session_factory(engine)
        app.state.db_session_factory = session_factory

        redis_client = get_redis_client(settings.redis)
        app.state.redis_client = redis_client

        app.state.s3 = S3Client(
            endpoint_url=settings.storage.endpoint_url,
            access_key=settings.storage.access_key,
            secret_key=settings.storage.secret_key,
            region=settings.storage.region,
            public_endpoint_url=settings.storage.public_endpoint_url,
        )

        async with session_scope(session_factory) as session:
            await seed_admin_user(
                session, email=settings.admin.email, password=settings.admin.password
            )

        # Live updates: this replica's sockets (hub) fed from one Redis channel shared by all
        # replicas (relay), so an alert raised or acted on anywhere reaches every browser.
        hub = ConnectionHub(queue_size=settings.alerts.ws_queue_size)
        relay = RedisRelay(redis_client, hub)
        dispatcher = build_dispatcher(settings.notify, publish=relay.publish)
        app.state.hub, app.state.relay, app.state.dispatcher = hub, relay, dispatcher
        background = [asyncio.create_task(relay.run(), name="ws-relay")]
        if settings.alerts.consumers_enabled:
            background += _start_alert_consumers(settings, session_factory, relay, dispatcher)

        log.info(
            "api_started",
            environment=settings.environment,
            notify_channels=dispatcher.channels,
            alert_consumers=settings.alerts.consumers_enabled,
        )
        try:
            yield
        finally:
            await _stop_tasks(background)
            await redis_client.aclose()
            await engine.dispose()
            log.info("api_stopped")

    app = FastAPI(title="GenAI-VMS API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(cameras_router, prefix="/api/v1")
    app.include_router(zones_router, prefix="/api/v1")
    app.include_router(topology_router, prefix="/api/v1")
    app.include_router(alerts_router, prefix="/api/v1")
    app.include_router(correlations_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")
    app.include_router(recordings_router, prefix="/api/v1")
    app.include_router(twin_router, prefix="/api/v1")
    app.include_router(tracks_router, prefix="/api/v1")
    app.include_router(internal_router, prefix="/api/v1")
    app.include_router(incidents_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")
    app.include_router(assistant_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(cases_router, prefix="/api/v1")
    app.include_router(timeline_router, prefix="/api/v1")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)  # noqa: S104


if __name__ == "__main__":
    main()
