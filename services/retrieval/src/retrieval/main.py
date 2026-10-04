"""Entrypoint for the retrieval service: text search (decompose → SigLIP → fuse → rerank) and
image search, over HTTP on :8010 (P4-D1…D3, P4-J1). Reached through the api, never by browsers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from vms_common.llm import LLMGateway
from vms_common.logging import configure_logging, get_logger
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory

from retrieval.adapters.catalog import Catalog
from retrieval.adapters.encoder import SiglipQueryEncoder
from retrieval.adapters.grounding import Grounder
from retrieval.adapters.knowledge import KnowledgeSearch, make_embedder
from retrieval.adapters.twins import TwinReader
from retrieval.adapters.vectors import VectorSearch
from retrieval.api.assistant_routes import router as assistant_router
from retrieval.api.routes import router
from retrieval.assistant.agent import Assistant
from retrieval.assistant.store import ChatStore
from retrieval.assistant.tools import ToolContext
from retrieval.grounding_service import GroundingService
from retrieval.jit import JitRefiner
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
        jit = JitRefiner(gateway, Catalog(sessions), s3)
        embedder = make_embedder(settings.knowledge.cache_dir)
        knowledge = KnowledgeSearch(qdrant, embedder)
        pipeline = SearchPipeline(
            settings=settings,
            encoder=encoder,
            vectors=VectorSearch(qdrant),
            catalog=Catalog(sessions),
            twins=TwinReader(s3),
            gateway=gateway,
            profile=gateway.profile,
            knowledge=knowledge,
            jit=jit,
        )
        app.state.knowledge = knowledge
        app.state.pipeline, app.state.encoder, app.state.profile = (
            pipeline,
            encoder,
            gateway.profile,
        )

        catalog = Catalog(sessions)
        await s3.ensure_bucket(settings.masks_bucket)
        app.state.grounding = GroundingService(Grounder(), s3, catalog, settings.masks_bucket)
        try:
            cameras = await catalog.camera_codes()
        except Exception as exc:  # the list only helps the model phrase tool arguments
            log.warning("camera_list_unavailable", error=str(exc))
            cameras = []
        tz = ZoneInfo(settings.site_timezone)
        chat_store = ChatStore(sessions)
        app.state.sessions, app.state.chat_store = sessions, chat_store
        app.state.assistant = Assistant(
            gateway=gateway,
            store=chat_store,
            ctx_factory=lambda evidence: ToolContext(
                sessions=sessions,
                pipeline=pipeline,
                tz=tz,
                evidence=evidence,
                archive_since=settings.archive_since,
            ),
            tz=tz,
            cameras=cameras,
        )

        # Weights load off the event loop so /health answers at once; /ready flips when done.
        loader = asyncio.create_task(asyncio.to_thread(encoder.load), name="siglip-load")
        text_loader = asyncio.create_task(asyncio.to_thread(embedder.load), name="knowledge-load")
        await pipeline.refresh_zones()
        log.info("retrieval_started", profile=gateway.profile, encoder=settings.siglip_model)
        try:
            yield
        finally:
            loader.cancel()
            text_loader.cancel()
            await gateway.aclose()
            await qdrant.close()
            await engine.dispose()

    app = FastAPI(title="GenAI-VMS retrieval", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.include_router(assistant_router)
    return app


def main() -> None:
    import uvicorn

    settings = RetrievalSettings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
