"""SigLIP 2 text and image encoder for queries, on CPU (design §10.1).

Same model, same normalisation as perception's `SiglipEmbedder`, so a query vector lands in the
space the indexed keyframes and crops were embedded in. Loaded lazily in a worker thread so the
service answers `/health` while the weights load; every call is a blocking torch forward pass
and is run with `asyncio.to_thread` by the caller.
"""

from __future__ import annotations

import io
import threading

import numpy as np


class SiglipQueryEncoder:
    def __init__(self, model_name: str, device: str = "cpu") -> None:
        self._model_name = model_name
        self._device = device
        self._lock = threading.Lock()
        self._model = None
        self._processor = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            import torch
            from transformers import AutoModel, AutoProcessor

            processor = AutoProcessor.from_pretrained(self._model_name)
            model = AutoModel.from_pretrained(self._model_name, dtype=torch.float32)
            model.to(self._device)
            model.eval()
            self._processor, self._model = processor, model

    def embed_text(self, texts: list[str]) -> np.ndarray:
        """`(n, 768)` float32, L2-normalised."""
        import torch

        self.load()
        assert self._processor is not None and self._model is not None  # noqa: S101
        # SigLIP was trained on lower-cased text.
        inputs = self._processor(
            text=[t.lower() for t in texts],
            padding="max_length",
            truncation=True,
            max_length=64,
            return_tensors="pt",
        )
        with torch.inference_mode():
            feats = self._model.get_text_features(input_ids=inputs["input_ids"].to(self._device))
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().astype(np.float32)

    def embed_image(self, data: bytes) -> np.ndarray:
        """`(768,)` float32, L2-normalised, for one encoded image."""
        import torch
        from PIL import Image

        self.load()
        assert self._processor is not None and self._model is not None  # noqa: S101
        image = Image.open(io.BytesIO(data)).convert("RGB")
        inputs = self._processor(images=[image], return_tensors="pt")
        with torch.inference_mode():
            feats = self._model.get_image_features(
                pixel_values=inputs["pixel_values"].to(self._device)
            )
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats[0].cpu().numpy().astype(np.float32)
