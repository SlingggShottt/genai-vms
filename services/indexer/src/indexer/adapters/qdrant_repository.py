"""Upserts one twin document's frame/track embeddings into Qdrant
(P2-J2). Point ids are deterministic (`vms_common.qdrant.point_ids`), so a
replayed `twinready.v1` message overwrites the same points rather than
duplicating them — Qdrant's `upsert` is "insert or overwrite by id" already,
no extra idempotency logic needed here (contrast with Postgres, where that
had to be built explicitly — see `indexer.adapters.repository`).
"""

from __future__ import annotations

import numpy as np
from qdrant_client import AsyncQdrantClient, models
from vms_common.contracts.twin import TwinV1
from vms_common.logging import get_logger
from vms_common.qdrant.collections import FRAMES_COLLECTION, SIGLIP_VECTOR_NAME, TRACKS_COLLECTION
from vms_common.qdrant.point_ids import frame_point_id, track_point_id

from indexer.domain.qdrant_payloads import build_frame_payload, build_track_payload

log = get_logger(__name__)


async def index_embeddings(
    client: AsyncQdrantClient,
    twin: TwinV1,
    embeddings: dict[str, np.ndarray],
) -> None:
    frame_vectors = embeddings["frame_vectors"]
    frame_points = []
    for frame in twin.frames:
        if not 0 <= frame.idx < len(frame_vectors):
            # frame.idx indexes the segment's full sampled-frame sequence
            # (see point_ids.frame_point_id's docstring); out of range means
            # the twin and its .npz disagree, which shouldn't happen for a
            # twin perception actually wrote — skip rather than crash the
            # whole segment's indexing over one bad frame.
            log.warning(
                "frame_idx_out_of_range_for_embeddings",
                segment_id=twin.segment_id,
                frame_idx=frame.idx,
                frame_vectors_len=len(frame_vectors),
            )
            continue
        frame_points.append(
            models.PointStruct(
                id=frame_point_id(twin.segment_id, frame.idx),
                vector={SIGLIP_VECTOR_NAME: frame_vectors[frame.idx].astype(np.float32).tolist()},
                payload=build_frame_payload(
                    frame,
                    camera_id=twin.camera_id,
                    site_id=twin.site_id,
                    segment_id=twin.segment_id,
                ),
            )
        )
    if frame_points:
        await client.upsert(FRAMES_COLLECTION, frame_points)

    track_vectors = embeddings["track_vectors"]
    track_points = []
    for track in twin.tracks:
        if not 0 <= track.embedding_index < len(track_vectors):
            log.warning(
                "track_embedding_index_out_of_range",
                segment_id=twin.segment_id,
                track_id=track.track_id,
                embedding_index=track.embedding_index,
                track_vectors_len=len(track_vectors),
            )
            continue
        track_points.append(
            models.PointStruct(
                id=track_point_id(track.track_id, twin.segment_id),
                vector={
                    SIGLIP_VECTOR_NAME: track_vectors[track.embedding_index]
                    .astype(np.float32)
                    .tolist()
                },
                payload=build_track_payload(
                    track, camera_id=twin.camera_id, segment_id=twin.segment_id
                ),
            )
        )
    if track_points:
        await client.upsert(TRACKS_COLLECTION, track_points)
