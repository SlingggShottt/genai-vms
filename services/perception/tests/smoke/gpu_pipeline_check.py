#!/usr/bin/env python
"""GPU smoke test (no Kafka/S3/Redis needed): loads YOLO11 + SigLIP2 for
real and runs detect -> track -> attributes -> embed on a real test image,
printing VRAM and latency. This is what P2-D6's benchmark numbers below
were actually measured with.

Usage:
    uv run --package vms-perception python tests/smoke/gpu_pipeline_check.py
"""

from __future__ import annotations

import io
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from perception.adapters.attributes import object_color, person_colors  # noqa: E402
from perception.adapters.detector import YoloDetector  # noqa: E402
from perception.adapters.embedder import SiglipEmbedder  # noqa: E402
from perception.adapters.tracker import PersistentTracker  # noqa: E402

TEST_IMAGE_URL = "https://ultralytics.com/images/bus.jpg"  # ultralytics' own reference image
CLASSES = [
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "backpack",
    "handbag",
    "suitcase",
]


class _FakeRedis:
    """In-memory stand-in so this script doesn't need a running Redis."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


def main() -> None:
    import asyncio

    if not torch.cuda.is_available():
        print("No CUDA GPU available — this check needs one to be meaningful.")
        sys.exit(1)

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    torch.cuda.reset_peak_memory_stats()

    data = urllib.request.urlopen(TEST_IMAGE_URL, timeout=30).read()  # noqa: S310
    img = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
    height, width, _ = img.shape

    detector = YoloDetector(
        model_name="yolo11s.pt", device="cuda:0", classes=CLASSES, confidence_threshold=0.4
    )
    embedder = SiglipEmbedder(device="cuda:0")
    print(f"models loaded, VRAM: {torch.cuda.memory_allocated() / 1e6:.0f} MB")

    tracker = PersistentTracker("cam01", redis_client=_FakeRedis())
    asyncio.run(tracker.restore())

    for _ in range(2):  # second pass so newly-appeared tracks are confirmed
        dets = detector.detect_batch([img])[0]
        boxes = np.array([d.bbox_xyxy for d in dets], dtype=np.float32)
        confs = np.array([d.confidence for d in dets], dtype=np.float32)
        class_ids = np.array([d.class_id for d in dets], dtype=np.int64)
        tracked = tracker.assign(boxes, confs, class_ids)

    print(f"detected+tracked {len(tracked)} objects:")
    crops = []
    for obj in tracked:
        category = detector.class_name(obj.class_id)
        x1, y1, x2, y2 = obj.bbox
        crop_rgb = img[int(y1 * height) : int(y2 * height), int(x1 * width) : int(x2 * width)]
        crop_bgr = np.ascontiguousarray(crop_rgb[:, :, ::-1])
        attr = (
            f"upper={(c := person_colors(crop_bgr))[0]} lower={c[1]}"
            if category == "person"
            else f"color={object_color(crop_bgr)}"
        )
        track_id = tracker.track_id_for(obj.track_num)
        print(f"  {track_id}: {category} conf={obj.confidence:.2f} {attr}")
        crops.append(crop_rgb)

    vecs = embedder.embed_images(crops)
    print(f"embeddings: shape={vecs.shape} dtype={vecs.dtype}")

    # Timing: warm batch-of-8 at 1080p, matching the P2-D6 numbers this
    # script produced (see ml/evaluation/results/).
    frames = [(np.random.rand(1080, 1920, 3) * 255).astype(np.uint8) for _ in range(8)]
    for _ in range(3):
        detector.detect_batch(frames)
    torch.cuda.synchronize()
    times = []
    for _ in range(10):
        t0 = time.time()
        detector.detect_batch(frames)
        torch.cuda.synchronize()
        times.append((time.time() - t0) * 1000)
    print(f"YOLO11s warm batch-of-8 (1080p, synthetic): mean={sum(times) / len(times):.1f} ms")
    print(f"peak VRAM this run: {torch.cuda.max_memory_allocated() / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
