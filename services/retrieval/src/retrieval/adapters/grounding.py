"""Object-level grounding (P4-J2): a box on a keyframe → a SAM 2.1-tiny mask, run-length encoded.

The design hosts this in the perception process on the GPU; here it runs on CPU in retrieval
(~1.2 s per keyframe, one image encoding for all the boxes on it) so the 4 GB card stays free
for the language models. Masks are cached in `vms-masks`, keyed by keyframe and boxes.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
from dataclasses import dataclass

import numpy as np

MODEL = "facebook/sam2.1-hiera-tiny"
MAX_MASK_WIDTH = 640  # masks are downscaled: the overlay is scaled up in the browser


@dataclass(frozen=True)
class MaskResult:
    track_id: str | None
    category: str | None
    bbox: tuple[float, float, float, float]  # normalised
    rle: dict  # {"counts": [...], "size": [h, w]}  (row-major, runs start with 0)


def rle_encode(mask: np.ndarray) -> dict:
    """Run lengths of a boolean mask, row-major, alternating 0-run, 1-run, … starting with 0."""
    flat = mask.astype(np.uint8).ravel()
    if flat.size == 0:
        return {"counts": [], "size": list(mask.shape)}
    change = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    bounds = np.concatenate(([0], change, [flat.size]))
    counts = np.diff(bounds).tolist()
    if flat[0] == 1:
        counts = [0, *counts]
    return {"counts": counts, "size": list(mask.shape)}


def rle_decode(rle: dict) -> np.ndarray:
    h, w = rle["size"]
    flat = np.zeros(h * w, dtype=bool)
    pos, value = 0, False
    for run in rle["counts"]:
        if value:
            flat[pos : pos + run] = True
        pos += run
        value = not value
    return flat.reshape(h, w)


def cache_key(keyframe_uri: str, boxes: list[tuple[float, float, float, float]]) -> str:
    raw = keyframe_uri + "|" + ",".join(f"{v:.3f}" for b in boxes for v in b)
    return hashlib.sha1(raw.encode()).hexdigest()  # noqa: S324 - a cache key, not a secret


class Grounder:
    def __init__(self, model_name: str = MODEL) -> None:
        self._name = model_name
        self._model = None
        self._processor = None
        self._lock = threading.Lock()  # one encoding at a time: CPU-bound and memory-hungry

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from transformers import Sam2Model, Sam2Processor

            self._processor = Sam2Processor.from_pretrained(self._name)
            self._model = Sam2Model.from_pretrained(self._name).eval()

    def segment(
        self, image_bytes: bytes, boxes: list[tuple[float, float, float, float]]
    ) -> list[np.ndarray]:
        """One boolean mask per normalised `(x1, y1, x2, y2)` box, at the image's resolution
        reduced to at most `MAX_MASK_WIDTH` wide."""
        import torch
        from PIL import Image

        self.load()
        assert self._model is not None and self._processor is not None  # noqa: S101
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = image.size
        px = [[b[0] * w, b[1] * h, b[2] * w, b[3] * h] for b in boxes]
        with self._lock:
            inputs = self._processor(images=image, input_boxes=[px], return_tensors="pt")
            with torch.inference_mode():
                out = self._model(**inputs, multimask_output=False)
            masks = self._processor.post_process_masks(out.pred_masks, inputs["original_sizes"])[0]
        masks = masks.reshape(len(boxes), -1, h, w)[:, 0].numpy().astype(bool)
        if w > MAX_MASK_WIDTH:
            nw, nh = MAX_MASK_WIDTH, round(h * MAX_MASK_WIDTH / w)
            masks = np.stack(
                [
                    np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize((nw, nh))) > 127
                    for m in masks
                ]
            )
        return list(masks)


def dump(results: list[MaskResult], width: int, height: int) -> bytes:
    return json.dumps(
        {
            "width": width,
            "height": height,
            "masks": [
                {"track_id": r.track_id, "category": r.category, "bbox": r.bbox, "rle": r.rle}
                for r in results
            ],
        }
    ).encode()
