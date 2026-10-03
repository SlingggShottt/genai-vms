"""Entrypoint for the api service: FastAPI app factory + uvicorn runner.

Implementation grows with each story — see docs/backlog.md and
docs/design_architecture.md §9 for the full endpoint surface this lands.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from vms_common.logging import configure_logging, get_logger
from vms_common.redis import get_redis_client
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory, session_scope

from api.adapters.users import seed_admin_user
from api.api.auth import router as auth_router
from api.api.cameras import router as cameras_router
from api.api.errors import register_exception_handlers
from api.api.health import router as health_router
from api.api.internal import router as internal_router
from api.api.middleware import RequestIDMiddleware
from api.api.recordings import router as recordings_router
from api.api.topology import router as topology_router
from api.api.tracks import router as tracks_router
from api.api.twin import router as twin_router
from api.api.users import router as users_router
from api.api.zones import router as zones_router
from api.settings import ApiSettings

log = get_logger(__name__)


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
        )

        async with session_scope(session_factory) as session:
            await seed_admin_user(
                session, email=settings.admin.email, password=settings.admin.password
            )

        log.info("api_started", environment=settings.environment)
        try:
            yield
        finally:
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
    app.include_router(recordings_router, prefix="/api/v1")
    app.include_router(twin_router, prefix="/api/v1")
    app.include_router(tracks_router, prefix="/api/v1")
    app.include_router(internal_router, prefix="/api/v1")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)  # noqa: S104


if __name__ == "__main__":
    main()
