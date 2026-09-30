"""Creates the three Qdrant collections from design_architecture.md §6.2:
`frames`, `tracks` (written by the indexer, P2-J2) and `knowledge` (created
empty here — written from events/incidents/daily reports starting phase 3,
outside this story's scope).

Idempotent, like `deploy/compose/scripts/create_topics.sh`'s
`--if-not-exists` Kafka topics: `ensure_collections` only creates a
collection that doesn't exist yet and never touches one that does, so it's
safe to call from both the one-shot bootstrap script and a service's own
startup.
"""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient, models

FRAMES_COLLECTION = "frames"
TRACKS_COLLECTION = "tracks"
KNOWLEDGE_COLLECTION = "knowledge"

SIGLIP_VECTOR_NAME = "siglip"
SIGLIP_VECTOR_SIZE = 768

KNOWLEDGE_DENSE_VECTOR_NAME = "dense"
KNOWLEDGE_DENSE_VECTOR_SIZE = 384  # bge-small-en-v1.5
KNOWLEDGE_SPARSE_VECTOR_NAME = "sparse"  # BM25, via FastEmbed


async def ensure_collections(client: AsyncQdrantClient) -> None:
    await _ensure_frames(client)
    await _ensure_tracks(client)
    await _ensure_knowledge(client)


async def _ensure_frames(client: AsyncQdrantClient) -> None:
    if await client.collection_exists(FRAMES_COLLECTION):
        return
    await client.create_collection(
        FRAMES_COLLECTION,
        vectors_config={
            SIGLIP_VECTOR_NAME: models.VectorParams(
                size=SIGLIP_VECTOR_SIZE, distance=models.Distance.COSINE
            )
        },
    )
    for field, schema in (
        ("camera_id", models.PayloadSchemaType.KEYWORD),
        ("site_id", models.PayloadSchemaType.KEYWORD),
        ("ts", models.PayloadSchemaType.INTEGER),
        ("categories", models.PayloadSchemaType.KEYWORD),
    ):
        await client.create_payload_index(FRAMES_COLLECTION, field, schema)


async def _ensure_tracks(client: AsyncQdrantClient) -> None:
    if await client.collection_exists(TRACKS_COLLECTION):
        return
    await client.create_collection(
        TRACKS_COLLECTION,
        vectors_config={
            SIGLIP_VECTOR_NAME: models.VectorParams(
                size=SIGLIP_VECTOR_SIZE, distance=models.Distance.COSINE
            )
        },
    )
    for field, schema in (
        ("camera_id", models.PayloadSchemaType.KEYWORD),
        ("category", models.PayloadSchemaType.KEYWORD),
        ("colors", models.PayloadSchemaType.KEYWORD),
        ("first_ts", models.PayloadSchemaType.INTEGER),
        ("zones", models.PayloadSchemaType.KEYWORD),
    ):
        await client.create_payload_index(TRACKS_COLLECTION, field, schema)


async def _ensure_knowledge(client: AsyncQdrantClient) -> None:
    if await client.collection_exists(KNOWLEDGE_COLLECTION):
        return
    await client.create_collection(
        KNOWLEDGE_COLLECTION,
        vectors_config={
            KNOWLEDGE_DENSE_VECTOR_NAME: models.VectorParams(
                size=KNOWLEDGE_DENSE_VECTOR_SIZE, distance=models.Distance.COSINE
            )
        },
        sparse_vectors_config={KNOWLEDGE_SPARSE_VECTOR_NAME: models.SparseVectorParams()},
    )
    for field, schema in (
        ("doc_type", models.PayloadSchemaType.KEYWORD),
        ("camera_ids", models.PayloadSchemaType.KEYWORD),
        ("ts_start", models.PayloadSchemaType.INTEGER),
        ("severity", models.PayloadSchemaType.KEYWORD),
    ):
        await client.create_payload_index(KNOWLEDGE_COLLECTION, field, schema)
