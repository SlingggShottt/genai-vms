"""Entrypoint for the indexer service: one Kafka consumer turning
`twinready.v1` into rows in `media.segments` / `vision.*` (P2-J1).
"""

from __future__ import annotations

import asyncio

from qdrant_client import AsyncQdrantClient
from vms_common.contracts.twinready import TwinReadyV1
from vms_common.logging import configure_logging, get_logger
from vms_common.metrics import serve as serve_metrics
from vms_common.qdrant.collections import ensure_collections
from vms_common.qdrant.knowledge import KnowledgeEmbedder
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory

from indexer.knowledge import EventKnowledgeConsumer, IncidentKnowledgeConsumer
from indexer.settings import IndexerSettings
from indexer.worker import IndexerConsumer

log = get_logger(__name__)

# Topic name is singular "twin" (design_architecture.md §5.2); the message
# schema_version is "twinready.v1" — same naming quirk as segment.v1 living
# on the plural vms.segments.v1 topic (see perception's twin_writer.py).
TWIN_TOPIC = "vms.twin.v1"


async def _amain() -> None:
    configure_logging()
    serve_metrics(9103)  # Prometheus scrape port, design §15
    settings = IndexerSettings()

    s3 = S3Client(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        region=settings.storage.region,
    )

    engine = create_engine(settings.db)
    session_factory = create_session_factory(engine)

    qdrant = AsyncQdrantClient(url=settings.qdrant.url, api_key=settings.qdrant.api_key or None)
    await ensure_collections(qdrant)

    consumer = IndexerConsumer(
        topic=TWIN_TOPIC,
        group_id=settings.consumer_group,
        bootstrap_servers=settings.kafka.bootstrap_servers,
        model=TwinReadyV1,
        dlq_topic=settings.kafka.dlq_topic,
        s3=s3,
        session_factory=session_factory,
        qdrant=qdrant,
    )

    # Text knowledge (event captions, incident reports): independent consumer groups, so a model
    # download or a slow embedding never delays indexing the twins.
    embedder = KnowledgeEmbedder(cache_dir=settings.knowledge.cache_dir or None)
    common = {
        "bootstrap_servers": settings.kafka.bootstrap_servers,
        "dlq_topic": settings.kafka.dlq_topic,
        "qdrant": qdrant,
        "embedder": embedder,
    }
    knowledge = [
        EventKnowledgeConsumer(
            topic="vms.events.v1", group_id=f"{settings.consumer_group}-events-knowledge", **common
        ),
        IncidentKnowledgeConsumer(
            topic="vms.incidents.v1",
            group_id=f"{settings.consumer_group}-incidents-knowledge",
            session_factory=session_factory,
            **common,
        ),
    ]
    tasks: list[asyncio.Task] = []

    async def run_knowledge(c) -> None:
        async with c:
            await c.run()

    try:
        tasks = [asyncio.create_task(run_knowledge(c), name=type(c).__name__) for c in knowledge]
        async with consumer:
            await consumer.run()
    finally:
        for t in tasks:
            t.cancel()
        await engine.dispose()
        await qdrant.close()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("indexer_stopped")


if __name__ == "__main__":
    main()
