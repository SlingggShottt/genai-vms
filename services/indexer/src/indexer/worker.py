"""Consumes `twinready.v1`, fetches its twin document + embeddings from
object storage, and indexes them into Postgres (P2-J1) and Qdrant (P2-J2).
"""

from __future__ import annotations

from aiokafka.structs import ConsumerRecord
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.contracts.embeddings import load_embeddings_npz
from vms_common.contracts.twin import TwinV1
from vms_common.contracts.twinready import TwinReadyV1
from vms_common.kafka.consumer import BaseConsumer
from vms_common.logging import bind_context, clear_context, get_logger
from vms_common.storage.s3 import S3Client
from vms_db.session import session_scope

from indexer.adapters.qdrant_repository import index_embeddings
from indexer.adapters.repository import index_twin

log = get_logger(__name__)


class IndexerConsumer(BaseConsumer[TwinReadyV1]):
    """Validate -> fetch twin+embeddings -> upsert Postgres -> upsert Qdrant -> commit.

    Every write here is idempotent (see `repository.index_twin` and
    `qdrant_repository.index_embeddings`), so if a later step in `handle`
    raises, `BaseConsumer`'s retry just redoes the whole thing safely.
    """

    def __init__(
        self,
        *,
        s3: S3Client,
        session_factory: async_sessionmaker,
        qdrant: AsyncQdrantClient,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._s3 = s3
        self._session_factory = session_factory
        self._qdrant = qdrant

    async def handle(self, message: TwinReadyV1, record: ConsumerRecord) -> None:
        bind_context(segment_id=message.segment_id, camera_id=message.camera_id)
        try:
            twin_bytes = await self._s3.get_bytes(message.twin_uri)
            twin = TwinV1.model_validate_json(twin_bytes)

            async with session_scope(self._session_factory) as session:
                await index_twin(session, message, twin)

            embeddings_bytes = await self._s3.get_bytes(message.embeddings_uri)
            embeddings = load_embeddings_npz(embeddings_bytes)
            await index_embeddings(self._qdrant, twin, embeddings)

            log.info("segment_indexed", segment_id=message.segment_id, tracks=len(twin.tracks))
        finally:
            clear_context()
