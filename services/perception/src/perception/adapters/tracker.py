"""Per-camera ByteTrack tracking with Redis-backed state so track ids
survive a worker restart (P2-D2, FR-PER-03).

Verified against the real installed `supervision==0.30.5` (no camera
needed — synthetic detections fed frame-by-frame):
  - `sv.ByteTrack` is soft-deprecated (warns, removal planned for v0.31;
    no replacement class exists yet in this version) but still the only
    tracker available and fully functional — used as-is, revisit when
    v0.31 actually drops it.
  - **A newly-seen detection does NOT appear in `update_with_detections`'s
    return value on the frame it first appears — it shows up starting the
    *next* frame** (a one-frame confirmation lag), even with
    `minimum_consecutive_frames=1` (the default). So the output can be
    *shorter* than the input; this is normal, not an error.
  - Output order tracks identity correctly regardless of input order
    (confirmed by feeding the same two objects in swapped order and
    checking `tracker_id` followed the right box), so bbox/tracker_id
    pairs from the *output* are trustworthy without needing to re-match
    against the original input list — but `class_id` must be read from
    the output too, for the same reason (an IoU/positional zip against
    the input is not safe once counts can differ).

Because of the above, `assign()` doesn't try to align its return value
1:1 with the input — it returns the tracker's own output set (bbox,
class_id, confidence, persistent track_num), which is not the same
detections list you gave it whenever a brand new object just appeared.

Persistent identity: `supervision.ByteTrack` doesn't expose a way to seed
its internal id counter, so this doesn't rely on it for cross-restart
identity at all. ByteTrack is used purely for frame-to-frame association
(its own session-local `tracker_id`); a separate counter *we* own and
checkpoint maps each session-local id to a persistent `track_num` the
first time it's seen. What survives a restart:
  - the next persistent track_num (never reuses a number used before the
    crash)
  - a snapshot of tracks active at the last checkpoint (track_num, last
    bbox), used for one-shot IoU re-association against the first batch
    of detections processed after a restore — a track whose new detection
    strongly overlaps a previously active track's last position keeps its
    old id; anything that doesn't match gets a fresh one.
This is a best-effort compromise, not true Kalman-state continuity
through a mid-track crash — see `perception.worker`'s module docstring
for the bigger picture.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass

import numpy as np
import supervision as sv
from redis.asyncio import Redis
from vms_common.logging import get_logger

from perception.domain.track_id import format_track_id

log = get_logger(__name__)

REDIS_KEY_PREFIX = "tracker:state:"
REDIS_STATE_TTL_SECONDS = 7 * 24 * 3600  # matches media.segments' typical retention horizon
REASSOCIATION_IOU_THRESHOLD = 0.3


@dataclass(frozen=True)
class TrackedObject:
    """One tracked detection from the tracker's own output set — see
    module docstring for why this isn't 1:1 with the input list."""

    bbox: tuple[float, float, float, float]
    confidence: float
    class_id: int
    track_num: int


@dataclass
class _ActiveTrack:
    track_num: int
    bbox: tuple[float, float, float, float]


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    intersection = (ix2 - ix1) * (iy2 - iy1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


class PersistentTracker:
    """One ByteTrack instance for one camera, with Redis checkpoint/restore."""

    def __init__(self, camera_id: str, *, redis_client: Redis) -> None:
        self._camera_id = camera_id
        self._redis = redis_client
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)  # ByteTrack deprecation, see docstring
            self._bytetrack = sv.ByteTrack()
        self._next_track_num = 0
        self._session_to_persistent: dict[int, int] = {}
        self._active: dict[int, _ActiveTrack] = {}
        self._pending_reassociation = False

    async def restore(self) -> None:
        """Load the last checkpoint from Redis, if any. Call once at startup."""
        raw = await self._redis.get(f"{REDIS_KEY_PREFIX}{self._camera_id}")
        if raw is None:
            return
        state = json.loads(raw)
        self._next_track_num = state.get("next_track_num", 0)
        self._active = {
            t["track_num"]: _ActiveTrack(t["track_num"], tuple(t["bbox"]))
            for t in state.get("active_tracks", [])
        }
        self._pending_reassociation = bool(self._active)
        log.info(
            "tracker_state_restored",
            camera_id=self._camera_id,
            next_track_num=self._next_track_num,
            active_tracks=len(self._active),
        )

    async def checkpoint(self, *, out_of_order: bool = False) -> None:
        """Persist current state to Redis. Skipped for out-of-order segments
        (P2-D2 AC) so a late/replayed segment can't corrupt the checkpoint.
        """
        if out_of_order:
            log.warning("tracker_checkpoint_skipped_out_of_order", camera_id=self._camera_id)
            return
        state = {
            "next_track_num": self._next_track_num,
            "active_tracks": [
                {"track_num": t.track_num, "bbox": list(t.bbox)} for t in self._active.values()
            ],
        }
        await self._redis.set(
            f"{REDIS_KEY_PREFIX}{self._camera_id}", json.dumps(state), ex=REDIS_STATE_TTL_SECONDS
        )

    def assign(
        self, boxes_xyxy: np.ndarray, confidences: np.ndarray, class_ids: np.ndarray
    ) -> list[TrackedObject]:
        """Run ByteTrack for one frame's detections. Returns the tracker's
        own output set — may be shorter than the input (new objects take
        one extra frame to confirm, see module docstring) and is not
        positionally aligned with it.
        """
        if len(boxes_xyxy) == 0:
            return []

        detections = sv.Detections(
            xyxy=boxes_xyxy, confidence=confidences, class_id=class_ids.astype(int)
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            tracked = self._bytetrack.update_with_detections(detections)

        if tracked.tracker_id is None:
            return []

        new_active: dict[int, _ActiveTrack] = {}
        result: list[TrackedObject] = []
        for session_id, box, conf, class_id in zip(
            tracked.tracker_id, tracked.xyxy, tracked.confidence, tracked.class_id, strict=True
        ):
            session_id = int(session_id)
            box_f = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
            if session_id not in self._session_to_persistent:
                self._session_to_persistent[session_id] = self._resolve_persistent_id(box_f)
            track_num = self._session_to_persistent[session_id]
            new_active[track_num] = _ActiveTrack(track_num, box_f)
            result.append(
                TrackedObject(
                    bbox=box_f,
                    confidence=float(conf),
                    class_id=int(class_id),
                    track_num=track_num,
                )
            )

        self._active = new_active
        return result

    def _resolve_persistent_id(self, box: tuple[float, float, float, float]) -> int:
        if self._pending_reassociation:
            best_id, best_iou = None, REASSOCIATION_IOU_THRESHOLD
            for old_id, prev in self._active.items():
                iou = _iou(box, prev.bbox)
                if iou > best_iou:
                    best_id, best_iou = old_id, iou
            if best_id is not None:
                del self._active[best_id]
                return best_id
        track_num = self._next_track_num
        self._next_track_num += 1
        return track_num

    def track_id_for(self, track_num: int) -> str:
        return format_track_id(self._camera_id, track_num)
