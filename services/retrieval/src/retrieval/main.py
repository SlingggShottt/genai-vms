"""Entrypoint for the retrieval service: text search (decompose → SigLIP → fuse → rerank) and
image search, over HTTP on :8010 (P4-D1…D3, P4-J1). Reached through the api, never by browsers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from vms_common.llm import LLMGateway
from vms_common.logging import configure_logging, get_logger
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory

from retrieval.adapters.catalog import Catalog
from retrieval.adapters.encoder import SiglipQueryEncoder
from retrieval.adapters.twins import TwinReader
from retrieval.adapters.vectors import VectorSearch
from retrieval.api.routes import router
from retrieval.pipeline import SearchPipeline
from retrieval.settings import RetrievalSettings

log = get_logger(__name__)


def create_app(settings: RetrievalSettings | None = None) -> FastAPI:
    settings = settings or RetrievalSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(level=settings.log_level)
        engine = create_engine(settings.db)
        sessions = create_session_factory(engine)
        qdrant = AsyncQdrantClient(url=settings.qdrant.url, api_key=settings.qdrant.api_key or None)
        s3 = S3Client(
            endpoint_url=settings.storage.endpoint_url,
            access_key=settings.storage.access_key,
            secret_key=settings.storage.secret_key,
            region=settings.storage.region,
        )
        gateway = LLMGateway.from_settings(redis_settings=settings.redis)
        encoder = SiglipQueryEncoder(settings.siglip_model, settings.encoder_device)
        pipeline = SearchPipeline(
            settings=settings,
            encoder=encoder,
            vectors=VectorSearch(qdrant),
            catalog=Catalog(sessions),
            twins=TwinReader(s3),
            gateway=gateway,
            profile=gateway.profile,
        )
        app.state.pipeline, app.state.encoder, app.state.profile = (
            pipeline,
            encoder,
            gateway.profile,
        )

        # Weights load off the event loop so /health answers at once; /ready flips when done.
        loader = asyncio.create_task(asyncio.to_thread(encoder.load), name="siglip-load")
        await pipeline.refresh_zones()
        log.info("retrieval_started", profile=gateway.profile, encoder=settings.siglip_model)
        try:
            yield
        finally:
            loader.cancel()
            await gateway.aclose()
            await qdrant.close()
            await engine.dispose()

    app = FastAPI(title="GenAI-VMS retrieval", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


def main() -> None:
    import uvicorn

    settings = RetrievalSettings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
