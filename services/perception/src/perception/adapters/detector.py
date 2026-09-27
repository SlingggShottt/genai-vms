"""Batched YOLO11 detection (design_architecture.md §7.1: "Batch frames
across cameras (batch <= 8) into YOLO11 FP16"; FR-PER-02: detect at least
person, bicycle, car, motorcycle, bus, truck, backpack, handbag, suitcase).

Batches here are just "a list of RGB frames" — deliberately camera-agnostic,
so the cross-camera batching design_architecture.md §7.1 asks for is the
orchestration layer's job (collect frames from concurrent camera workers,
call `detect_batch` once <= max_batch_size frames are ready), not this
adapter's.

Verified against the real installed `ultralytics==8.4.163` on an RTX 3050
(yolo11n, random-noise frames — confirms the pipeline runs end to end and
correctly finds nothing in noise; not a detection-quality check). That
ultralytics version renamed `predict(half=...)` to `predict(quantize=16)`
for FP16 (`half` still works but warns as deprecated) — used directly here
to avoid the warning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from ultralytics import YOLO


@dataclass(frozen=True)
class Detection:
    bbox_xyxy: tuple[float, float, float, float]  # normalized [0,1]
    category: str
    class_id: int  # YOLO's own numeric id for `category` — tracker.assign() needs this
    confidence: float


class YoloDetector:
    """Wraps one YOLO11 model instance for batched inference."""

    def __init__(
        self,
        *,
        model_name: str = "yolo11s.pt",
        device: str = "cuda:0",
        classes: list[str] | None = None,
        confidence_threshold: float = 0.4,
    ) -> None:
        self._model = YOLO(model_name)
        self._model.to(device)
        self._device = device
        self._confidence_threshold = confidence_threshold
        self._class_filter: list[int] | None = None
        if classes is not None:
            name_to_id = {name: idx for idx, name in self._model.names.items()}
            unknown = [c for c in classes if c not in name_to_id]
            if unknown:
                raise ValueError(f"unknown class names for {model_name}: {unknown}")
            self._class_filter = [name_to_id[c] for c in classes]

    def detect_batch(self, frames_rgb: list[np.ndarray]) -> list[list[Detection]]:
        """Run detection on a batch (<=8 recommended) of RGB frames; returns
        one detection list per input frame, in the same order."""
        if not frames_rgb:
            return []
        results = self._model.predict(
            frames_rgb,
            conf=self._confidence_threshold,
            classes=self._class_filter,
            device=self._device,
            quantize=16 if self._device != "cpu" else None,
            verbose=False,
        )
        return [self._to_detections(result) for result in results]

    def _to_detections(self, result: object) -> list[Detection]:
        height, width = result.orig_shape
        detections = []
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            class_id = int(box.cls[0])
            detections.append(
                Detection(
                    bbox_xyxy=(x1 / width, y1 / height, x2 / width, y2 / height),
                    category=self._model.names[class_id],
                    class_id=class_id,
                    confidence=float(box.conf[0]),
                )
            )
        return detections

    def class_name(self, class_id: int) -> str:
        """Reverse lookup — used to turn a tracked output's numeric
        `class_id` back into a category name (see `adapters.tracker`)."""
        return self._model.names[class_id]
