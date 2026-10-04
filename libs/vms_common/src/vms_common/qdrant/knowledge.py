"""The `knowledge` collection: event captions, incident-report sections and daily reports as
text, searchable by meaning (bge-small dense vectors) and by words (BM25 sparse vectors), fused
with reciprocal rank fusion on the Qdrant server (design §6.2, §10.1).

Writers (the indexer) and readers (retrieval) share this module so the two always embed the same
way. The embedders are ONNX models run by FastEmbed on CPU, loaded lazily in the calling thread;
call `embed` through `asyncio.to_thread` from async code.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from vms_common.qdrant.collections import (
    KNOWLEDGE_COLLECTION,
    KNOWLEDGE_DENSE_VECTOR_NAME,
    KNOWLEDGE_SPARSE_VECTOR_NAME,
)

DENSE_MODEL = "BAAI/bge-small-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"

DOC_EVENT = "event_caption"
DOC_INCIDENT = "incident_section"
DOC_DAILY = "daily_report"


@dataclass
class KnowledgeDoc:
    point_id: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Embedded:
    dense: list[float]
    sparse: models.SparseVector


class KnowledgeEmbedder:
    def __init__(
        self,
        dense_model: str = DENSE_MODEL,
        sparse_model: str = SPARSE_MODEL,
        cache_dir: str | None = None,
    ) -> None:
        self._dense_name, self._sparse_name = dense_model, sparse_model
        # FastEmbed's default is a temp directory, which is lost on reboot and re-downloaded.
        self._cache_dir = cache_dir
        self._dense = None
        self._sparse = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._dense is not None

    def load(self) -> None:
        with self._lock:
            if self._dense is not None:
                return
            from fastembed import SparseTextEmbedding, TextEmbedding

            self._dense = TextEmbedding(model_name=self._dense_name, cache_dir=self._cache_dir)
            self._sparse = SparseTextEmbedding(
                model_name=self._sparse_name, cache_dir=self._cache_dir
            )

    def embed(self, texts: list[str], *, query: bool = False) -> list[Embedded]:
        self.load()
        assert self._dense is not None and self._sparse is not None  # noqa: S101
        if query:
            # a list, always: query_embed("text") iterates the string in this fastembed version
            dense = [list(map(float, v)) for v in self._dense.query_embed(list(texts))]
            sparse = list(self._sparse.query_embed(list(texts)))
        else:
            dense = [list(map(float, v)) for v in self._dense.embed(texts)]
            sparse = list(self._sparse.embed(texts))
        return [
            Embedded(d, models.SparseVector(indices=s.indices.tolist(), values=s.values.tolist()))
            for d, s in zip(dense, sparse, strict=True)
        ]


async def upsert_docs(
    client: AsyncQdrantClient, embedder: KnowledgeEmbedder, docs: list[KnowledgeDoc]
) -> None:
    if not docs:
        return
    vectors = await asyncio.to_thread(embedder.embed, [d.text for d in docs])
    await client.upsert(
        KNOWLEDGE_COLLECTION,
        points=[
            models.PointStruct(
                id=d.point_id,
                vector={
                    KNOWLEDGE_DENSE_VECTOR_NAME: v.dense,
                    KNOWLEDGE_SPARSE_VECTOR_NAME: v.sparse,
                },
                payload={**d.payload, "text": d.text},
            )
            for d, v in zip(docs, vectors, strict=True)
        ],
    )


def _filter(
    doc_types: list[str] | None,
    camera_ids: list[str] | None,
    since_ms: int | None,
    until_ms: int | None,
    exclude_ref_ids: list[str] | None,
) -> models.Filter | None:
    must: list[models.Condition] = []
    must_not: list[models.Condition] = []
    if doc_types:
        must.append(models.FieldCondition(key="doc_type", match=models.MatchAny(any=doc_types)))
    if camera_ids:
        must.append(models.FieldCondition(key="camera_ids", match=models.MatchAny(any=camera_ids)))
    if since_ms is not None:
        must.append(models.FieldCondition(key="ts_end", range=models.Range(gte=since_ms)))
    if until_ms is not None:
        must.append(models.FieldCondition(key="ts_start", range=models.Range(lte=until_ms)))
    if exclude_ref_ids:
        must_not.append(
            models.FieldCondition(key="ref_id", match=models.MatchAny(any=exclude_ref_ids))
        )
    if not must and not must_not:
        return None
    return models.Filter(must=must or None, must_not=must_not or None)


async def search_docs(
    client: AsyncQdrantClient,
    embedder: KnowledgeEmbedder,
    query: str,
    *,
    doc_types: list[str] | None = None,
    camera_ids: list[str] | None = None,
    since_ms: int | None = None,
    until_ms: int | None = None,
    exclude_ref_ids: list[str] | None = None,
    limit: int = 10,
) -> list[models.ScoredPoint]:
    """Hybrid search: dense and BM25 candidates fused on the server with RRF."""
    (q,) = await asyncio.to_thread(embedder.embed, [query], query=True)
    flt = _filter(doc_types, camera_ids, since_ms, until_ms, exclude_ref_ids)
    res = await client.query_points(
        KNOWLEDGE_COLLECTION,
        prefetch=[
            models.Prefetch(
                query=q.dense, using=KNOWLEDGE_DENSE_VECTOR_NAME, filter=flt, limit=limit * 3
            ),
            models.Prefetch(
                query=q.sparse, using=KNOWLEDGE_SPARSE_VECTOR_NAME, filter=flt, limit=limit * 3
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    return list(res.points)
