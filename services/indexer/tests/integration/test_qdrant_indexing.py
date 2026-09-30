"""P2-J2 AC, verified against a real Qdrant (testcontainers):
- bootstrap creates `frames`/`tracks`/`knowledge` with the right vector config
- `index_embeddings` upserts with deterministic ids — replay overwrites,
  doesn't duplicate
- a filtered search (camera_id + time range) returns the expected point

Run via `make test-int` (needs Docker).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from indexer.adapters.qdrant_repository import index_embeddings
from qdrant_client import AsyncQdrantClient, models
from vms_common.contracts.embeddings import load_embeddings_npz
from vms_common.contracts.twin import TwinV1
from vms_common.qdrant.collections import (
    FRAMES_COLLECTION,
    KNOWLEDGE_COLLECTION,
    SIGLIP_VECTOR_NAME,
    TRACKS_COLLECTION,
)
from vms_common.qdrant.point_ids import frame_point_id, track_point_id

pytestmark = pytest.mark.integration

FIXTURES = (
    Path(__file__).resolve().parents[4] / "libs" / "vms_common" / "src" / "vms_common" / "fixtures"
)


def _load_twin() -> TwinV1:
    return TwinV1.model_validate_json((FIXTURES / "twin_v1.json").read_text())


def _load_embeddings() -> dict:
    return load_embeddings_npz((FIXTURES / "embeddings.npz").read_bytes())


async def test_bootstrap_creates_all_three_collections_with_expected_vector_config(
    qdrant_client: AsyncQdrantClient,
) -> None:
    for name in (FRAMES_COLLECTION, TRACKS_COLLECTION, KNOWLEDGE_COLLECTION):
        assert await qdrant_client.collection_exists(name)

    frames_info = await qdrant_client.get_collection(FRAMES_COLLECTION)
    frames_vectors = frames_info.config.params.vectors
    assert frames_vectors[SIGLIP_VECTOR_NAME].size == 768
    assert frames_vectors[SIGLIP_VECTOR_NAME].distance == models.Distance.COSINE

    knowledge_info = await qdrant_client.get_collection(KNOWLEDGE_COLLECTION)
    assert knowledge_info.config.params.sparse_vectors is not None
    assert "sparse" in knowledge_info.config.params.sparse_vectors


async def test_bootstrap_is_idempotent(qdrant_client: AsyncQdrantClient) -> None:
    from vms_common.qdrant.collections import ensure_collections

    # Calling it again (as the fixture already did once) must not raise.
    await ensure_collections(qdrant_client)
    assert await qdrant_client.collection_exists(FRAMES_COLLECTION)


async def test_replaying_index_embeddings_does_not_duplicate_points(
    qdrant_client: AsyncQdrantClient,
) -> None:
    twin = _load_twin()
    embeddings = _load_embeddings()

    for _ in range(2):
        await index_embeddings(qdrant_client, twin, embeddings)

    frames_count = await qdrant_client.count(FRAMES_COLLECTION, exact=True)
    tracks_count = await qdrant_client.count(TRACKS_COLLECTION, exact=True)

    # Fixture has 1 frame (idx=1) and 1 track (embedding_index=0).
    assert frames_count.count == 1
    assert tracks_count.count == 1

    frame_point = await qdrant_client.retrieve(
        FRAMES_COLLECTION, ids=[frame_point_id(twin.segment_id, twin.frames[0].idx)]
    )
    assert frame_point[0].payload["camera_id"] == "cam03"

    track_point = await qdrant_client.retrieve(
        TRACKS_COLLECTION, ids=[track_point_id(twin.tracks[0].track_id, twin.segment_id)]
    )
    assert track_point[0].payload["track_id"] == "cam03-t412"


async def test_filtered_search_by_camera_and_time_range_returns_the_expected_point(
    qdrant_client: AsyncQdrantClient,
) -> None:
    twin = _load_twin()
    embeddings = _load_embeddings()
    await index_embeddings(qdrant_client, twin, embeddings)

    frame_ts_ms = int(twin.frames[0].ts.timestamp() * 1000)
    query_vector = embeddings["frame_vectors"][twin.frames[0].idx].astype("float32").tolist()

    hits = await qdrant_client.query_points(
        FRAMES_COLLECTION,
        query=query_vector,
        using=SIGLIP_VECTOR_NAME,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="camera_id", match=models.MatchValue(value=twin.camera_id)
                ),
                models.FieldCondition(
                    key="ts",
                    range=models.Range(gte=frame_ts_ms - 1000, lte=frame_ts_ms + 1000),
                ),
            ]
        ),
        limit=5,
    )

    assert [p.id for p in hits.points] == [frame_point_id(twin.segment_id, twin.frames[0].idx)]

    # A different camera_id must not match, proving the filter is load-bearing.
    miss = await qdrant_client.query_points(
        FRAMES_COLLECTION,
        query=query_vector,
        using=SIGLIP_VECTOR_NAME,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="camera_id", match=models.MatchValue(value="cam99"))]
        ),
        limit=5,
    )
    assert miss.points == []
