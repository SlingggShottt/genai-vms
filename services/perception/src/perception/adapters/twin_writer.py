"""Writes the digital twin document + embeddings to object storage and
publishes `twinready.v1` (P2-D4, FR-PER-05). Topic is `vms.twin.v1`
(design_architecture.md §5.2 — topic name is singular "twin", the message
schema_version is "twinready.v1"; same naming quirk as segment.v1 living
on the plural `vms.segments.v1` topic).
"""

from __future__ import annotations

from collections import Counter

from vms_common.contracts.embeddings import build_embeddings_npz
from vms_common.contracts.twin import TwinV1
from vms_common.contracts.twinready import TwinReadyV1
from vms_common.kafka.producer import KafkaProducerClient
from vms_common.storage.s3 import S3Client

from perception.domain.segmenting import build_embeddings_key, build_twin_key

TWIN_TOPIC = "vms.twin.v1"


async def write_twin(
    twin: TwinV1,
    *,
    frame_vectors: object,
    frame_ts: list[str],
    track_vectors: object,
    track_ids: list[str],
    s3: S3Client,
    producer: KafkaProducerClient,
    perception_version: str,
) -> TwinReadyV1:
    """Upload `twin` + its embeddings, then publish `twinready.v1`."""
    twin_key = build_twin_key(twin.camera_id, twin.start_ts, twin.segment_id)
    embeddings_key = build_embeddings_key(twin.camera_id, twin.start_ts, twin.segment_id)
    twin_uri = f"s3://vms-twins/{twin_key}"
    embeddings_uri = f"s3://vms-twins/{embeddings_key}"

    await s3.put_bytes(
        twin_uri, twin.model_dump_json().encode("utf-8"), content_type="application/json"
    )
    npz_bytes = build_embeddings_npz(
        frame_vectors=frame_vectors,
        frame_ts=frame_ts,
        track_vectors=track_vectors,
        track_ids=track_ids,
    )
    await s3.put_bytes(embeddings_uri, npz_bytes, content_type="application/octet-stream")

    counts = Counter(obj.category for frame in twin.frames for obj in frame.objects)
    message = TwinReadyV1(
        site_id=twin.site_id,
        camera_id=twin.camera_id,
        segment_id=twin.segment_id,
        start_ts=twin.start_ts,
        end_ts=twin.end_ts,
        twin_uri=twin_uri,
        embeddings_uri=embeddings_uri,
        sample_fps=twin.sample_fps,
        counts=dict(counts),
        track_ids=[t.track_id for t in twin.tracks],
        perception_version=perception_version,
    )
    await producer.send(TWIN_TOPIC, key=twin.camera_id, message=message)
    return message
