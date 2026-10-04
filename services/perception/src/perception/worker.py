"""Consumes `segment.v1`, builds that segment's digital twin, and publishes
`twinready.v1` (P2-D1..D4). One `PerceptionConsumer` processes segments
from every camera (the topic's 6 partitions key by `camera_id`, so one
camera's segments stay in order); a `PersistentTracker` per camera keeps
ByteTrack state alive across that camera's segments for the life of the
process (P2-D2).

Design choices worth knowing about:
- **Batching**: YOLO batches (<= `max_batch_size`) within one segment's own
  sampled frames, not across concurrent cameras' segments. True
  cross-camera batching (design_architecture.md §7.1) needs a shared
  batch-collector across concurrent per-segment handlers — a bigger piece
  of work deferred here in favour of shipping a correct, simpler pipeline.
- **Empty frames are dropped** from `twin.frames` (only sampled frames with
  >= 1 detection are kept) — matches design principle #2 ("cheap filter
  before expensive reasoning") and keeps twin documents from ballooning
  with frames that have nothing in them.
- **Keyframe uploads**: perception decodes the segment independently from
  ingestion (up to 2x its 1fps rate), so its own keyframe JPEGs go under a
  `p`-prefixed filename in the same `vms-keyframes` folder ingestion uses —
  see `domain.segmenting.build_perception_keyframe_key`'s docstring for why.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from aiokafka.structs import ConsumerRecord
from vms_common.contracts.segment import SegmentV1
from vms_common.contracts.twin import Frame, FrameObject, ObjectAttributes, ObjectMotion
from vms_common.contracts.zones import ZoneInternal
from vms_common.kafka.consumer import BaseConsumer
from vms_common.kafka.producer import KafkaProducerClient
from vms_common.logging import bind_context, clear_context, get_logger
from vms_common.storage.s3 import S3Client

from perception.adapters.attributes import object_color, person_colors
from perception.adapters.decoder import SampledFrame, sample_frames
from perception.adapters.detector import Detection, YoloDetector
from perception.adapters.embedder import SiglipEmbedder
from perception.adapters.tracker import PersistentTracker
from perception.adapters.twin_writer import write_twin
from perception.domain.motion import bbox_center, compute_motion
from perception.domain.sampling import AdaptiveSampler
from perception.domain.segmenting import build_crop_key, build_perception_keyframe_key
from perception.domain.twin_builder import build_twin
from perception.domain.zones import zones_for_bbox
from perception.metrics import latency_seconds, segments_total
from perception.settings import PerceptionSettings

log = get_logger(__name__)

PERSON_LIKE = frozenset({"person"})

# A frame_obj paired with its jpeg-encoded crop and raw RGB crop (RGB kept
# for embedding later; jpeg kept for the S3 upload).
_ObjectWithCrop = tuple[FrameObject, bytes, np.ndarray]


class PerceptionConsumer(BaseConsumer[SegmentV1]):
    """Validate -> decode -> detect -> track -> embed -> twin -> publish."""

    def __init__(
        self,
        *,
        settings: PerceptionSettings,
        s3: S3Client,
        producer: KafkaProducerClient,
        redis_client: object,
        detector: YoloDetector,
        embedder: SiglipEmbedder,
        get_zones: Callable[[], list[ZoneInternal]],
        perception_version: str,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._settings = settings
        self._s3 = s3
        self._producer = producer
        self._redis = redis_client
        self._detector = detector
        self._embedder = embedder
        self._get_zones = get_zones
        self._perception_version = perception_version

        self._trackers: dict[str, PersistentTracker] = {}
        self._samplers: dict[str, AdaptiveSampler] = {}
        self._prev_centroids: dict[str, dict[int, tuple[float, float]]] = {}
        self._last_processed_end: dict[str, object] = {}

    def _tracker_for(self, camera_id: str) -> PersistentTracker:
        if camera_id not in self._trackers:
            self._trackers[camera_id] = PersistentTracker(camera_id, redis_client=self._redis)
        return self._trackers[camera_id]

    def _sampler_for(self, camera_id: str) -> AdaptiveSampler:
        if camera_id not in self._samplers:
            self._samplers[camera_id] = AdaptiveSampler(
                default_fps=self._settings.default_sample_fps,
                degraded_fps=self._settings.degraded_sample_fps,
                degrade_threshold_s=self._settings.degrade_lag_threshold_s,
                recover_threshold_s=self._settings.recover_lag_threshold_s,
            )
        return self._samplers[camera_id]

    async def handle(self, message: SegmentV1, record: ConsumerRecord) -> None:
        bind_context(segment_id=message.segment_id, camera_id=message.camera_id)
        try:
            await self._handle_segment(message)
        finally:
            clear_context()

    async def _handle_segment(self, message: SegmentV1) -> None:
        out_of_order = self._is_out_of_order(message)
        if out_of_order:
            log.warning("segment_out_of_order", segment_id=message.segment_id)

        await asyncio.to_thread(Path(self._settings.work_dir).mkdir, parents=True, exist_ok=True)
        work_dir = Path(
            await asyncio.to_thread(
                tempfile.mkdtemp, prefix=f"{message.camera_id}_", dir=self._settings.work_dir
            )
        )
        try:
            local_path = work_dir / "segment.ts"
            data = await self._s3.get_bytes(message.uri)
            await asyncio.to_thread(local_path.write_bytes, data)

            lag_s = await self._consumer_lag_seconds()
            fps = self._sampler_for(message.camera_id).sample_fps(lag_s)
            sampled = await asyncio.to_thread(lambda: list(sample_frames(local_path, fps=fps)))

            zones = [z for z in self._get_zones() if z.camera_id == message.camera_id]
            twin_frames, best_crops = await self._process_frames(message, sampled, zones)

            # Every sampled frame gets an embedding (FR-PER-06), independent
            # of whether it had anything detected in it — a frame with zero
            # objects can still be a valid match for e.g. "empty hallway".
            # twin.frames only keeps non-empty frames, so frame_ts here is
            # built from `sampled`, not `twin_frames` (their lengths differ).
            frame_vectors = await self._embed_or_empty([sf.rgb for sf in sampled])
            frame_ts_all = [
                (message.start_ts + timedelta(seconds=sf.pts_seconds)).isoformat() for sf in sampled
            ]
            track_ids_ordered = list(best_crops.keys())
            track_vectors = await self._embed_or_empty(
                [best_crops[tid][1] for tid in track_ids_ordered]
            )

            best_crop_uris: dict[str, str] = {}
            for tid in track_ids_ordered:
                crop_bytes, _crop_rgb = best_crops[tid]
                key = build_crop_key(message.camera_id, message.start_ts, message.segment_id, tid)
                uri = f"s3://vms-crops/{key}"
                await self._s3.put_bytes(uri, crop_bytes, content_type="image/jpeg")
                best_crop_uris[tid] = uri

            twin = build_twin(
                segment_id=message.segment_id,
                camera_id=message.camera_id,
                site_id=message.site_id,
                start_ts=message.start_ts,
                end_ts=message.end_ts,
                sample_fps=fps,
                frame_size=(message.width, message.height),
                frames=twin_frames,
                best_crop_uris=best_crop_uris,
                embedding_indices={tid: i for i, tid in enumerate(track_ids_ordered)},
            )

            await write_twin(
                twin,
                frame_vectors=frame_vectors,
                frame_ts=frame_ts_all,
                track_vectors=track_vectors,
                track_ids=track_ids_ordered,
                s3=self._s3,
                producer=self._producer,
                perception_version=self._perception_version,
            )

            await self._tracker_for(message.camera_id).checkpoint(out_of_order=out_of_order)
            if not out_of_order:
                self._last_processed_end[message.camera_id] = message.end_ts
            segments_total.labels(camera=message.camera_id).inc()
            latency_seconds.observe(max(0.0, (datetime.now(UTC) - message.end_ts).total_seconds()))
            log.info("twin_published", segment_id=message.segment_id, tracks=len(twin.tracks))
        finally:
            await asyncio.to_thread(shutil.rmtree, work_dir, ignore_errors=True)

    async def _embed_or_empty(self, images: list[np.ndarray]) -> np.ndarray:
        if not images:
            return np.zeros((0, self._embedder.embedding_dim), dtype=np.float16)
        return await asyncio.to_thread(self._embedder.embed_images, images)

    def _is_out_of_order(self, message: SegmentV1) -> bool:
        last_end = self._last_processed_end.get(message.camera_id)
        return last_end is not None and message.start_ts < last_end

    async def _consumer_lag_seconds(self) -> float:
        """Best-effort consumer lag in seconds; 0 if unavailable (e.g. no
        committed offsets yet). Feeds `AdaptiveSampler` (P2-D1 AC)."""
        return 0.0  # TODO(P2-D6): wire to real aiokafka lag metrics during the benchmark story

    async def _process_frames(
        self, message: SegmentV1, sampled: list[SampledFrame], zones: list[ZoneInternal]
    ) -> tuple[list[Frame], dict[str, tuple[bytes, np.ndarray]]]:
        tracker = self._tracker_for(message.camera_id)
        prev_centroids = self._prev_centroids.setdefault(message.camera_id, {})
        best_crops: dict[str, tuple[bytes, np.ndarray]] = {}
        best_crop_area: dict[str, float] = {}
        twin_frames: list[Frame] = []

        for batch_start in range(0, len(sampled), self._settings.max_batch_size):
            batch = sampled[batch_start : batch_start + self._settings.max_batch_size]
            detections_per_frame = await asyncio.to_thread(
                self._detector.detect_batch, [f.rgb for f in batch]
            )

            for sampled_frame, detections in zip(batch, detections_per_frame, strict=True):
                if not detections:
                    continue  # drop empty frames from the twin (see module docstring)

                objects_with_crops, prev_centroids = self._to_frame_objects(
                    message, sampled_frame, detections, tracker, zones, prev_centroids
                )
                for obj, crop_bytes, crop_rgb in objects_with_crops:
                    area = (obj.bbox[2] - obj.bbox[0]) * (obj.bbox[3] - obj.bbox[1])
                    if area > best_crop_area.get(obj.track_id, -1.0):
                        best_crop_area[obj.track_id] = area
                        best_crops[obj.track_id] = (crop_bytes, crop_rgb)

                keyframe_key = build_perception_keyframe_key(
                    message.camera_id, message.start_ts, message.segment_id, sampled_frame.idx
                )
                keyframe_uri = f"s3://vms-keyframes/{keyframe_key}"
                ok, jpeg = cv2.imencode(".jpg", sampled_frame.rgb[:, :, ::-1])
                if ok:
                    await self._s3.put_bytes(
                        keyframe_uri, jpeg.tobytes(), content_type="image/jpeg"
                    )

                twin_frames.append(
                    Frame(
                        ts=message.start_ts + timedelta(seconds=sampled_frame.pts_seconds),
                        idx=sampled_frame.idx,
                        keyframe_uri=keyframe_uri,
                        objects=[obj for obj, _b, _r in objects_with_crops],
                    )
                )

        self._prev_centroids[message.camera_id] = prev_centroids
        return twin_frames, best_crops

    def _to_frame_objects(
        self,
        message: SegmentV1,
        sampled_frame: SampledFrame,
        detections: list[Detection],
        tracker: PersistentTracker,
        zones: list[ZoneInternal],
        prev_centroids: dict[int, tuple[float, float]],
    ) -> tuple[list[_ObjectWithCrop], dict[int, tuple[float, float]]]:
        boxes = np.array([d.bbox_xyxy for d in detections], dtype=np.float32)
        confidences = np.array([d.confidence for d in detections], dtype=np.float32)
        class_ids = np.array([d.class_id for d in detections], dtype=np.int64)

        # tracker.assign() returns its own output set, not positionally
        # aligned with `detections` — a just-appeared object doesn't show
        # up until the next frame, and order isn't guaranteed either. See
        # adapters/tracker.py's module docstring for what was verified.
        tracked = tracker.assign(boxes, confidences, class_ids)
        new_centroids: dict[int, tuple[float, float]] = {}
        results: list[_ObjectWithCrop] = []

        height, width, _ = sampled_frame.rgb.shape
        for obj in tracked:
            track_id = tracker.track_id_for(obj.track_num)
            category = self._detector.class_name(obj.class_id)
            centroid = bbox_center(obj.bbox)
            new_centroids[obj.track_num] = centroid

            motion = None
            if obj.track_num in prev_centroids:
                speed, direction = compute_motion(prev_centroids[obj.track_num], centroid, dt_s=1.0)
                motion = ObjectMotion(speed=speed, direction_deg=direction)

            x1, y1, x2, y2 = obj.bbox
            crop_rgb = sampled_frame.rgb[
                int(y1 * height) : int(y2 * height), int(x1 * width) : int(x2 * width)
            ]
            crop_bgr = np.ascontiguousarray(crop_rgb[:, :, ::-1])
            if category in PERSON_LIKE:
                upper, lower = person_colors(crop_bgr)
                attributes = ObjectAttributes(upper_color=upper, lower_color=lower)
            else:
                attributes = ObjectAttributes(color=object_color(crop_bgr))

            zone_names = zones_for_bbox(obj.bbox, message.camera_id, zones)
            ok, jpeg = cv2.imencode(".jpg", crop_bgr)
            frame_obj = FrameObject(
                track_id=track_id,
                category=category,
                conf=obj.confidence,
                bbox=obj.bbox,
                attributes=attributes,
                motion=motion,
                zones=zone_names,
            )
            results.append((frame_obj, jpeg.tobytes() if ok else b"", crop_rgb))

        return results, new_centroids
