"""SigLIP 2 image embeddings (FR-PER-06: keyframe embeddings every 2s and
one best-crop embedding per track per segment, FP16, L2-normalized).

Verified against the real installed `transformers==4.57.6` (uv's resolved
pin; 4.55.4 was the first version tried and also worked) + `torch==2.6.0
+cu124` on an RTX 3050: `google/siglip2-base-patch16-224` loads as a
`SiglipModel` (no separate `Siglip2*` class — same architecture serves
both checkpoints), `get_image_features(pixel_values=...)` returns
`(batch, 768)`, matching design_architecture.md §6.2's "siglip: 768-d,
cosine". `config.projection_dim` doesn't exist on this model — the
embedding dim is `config.vision_config.hidden_size` (confirmed against
the actual output shape, not just the config). Warm batch-of-8 GPU
inference: ~35ms, ~800 MB peak VRAM.

NOTE: `transformers>=5.0` requires a newer torch than 2.6.0 (imports
`torch.nn.attention.flex_attention.AuxRequest`, added after 2.6) — pinned
below 5.0 in `pyproject.toml` for that reason, not by choice.
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor


class SiglipEmbedder:
    """Wraps one SigLIP 2 model instance for batched image embedding."""

    def __init__(
        self, *, model_name: str = "google/siglip2-base-patch16-224", device: str = "cuda:0"
    ) -> None:
        self._device = device
        self._dtype = torch.float16 if device != "cpu" else torch.float32
        self._processor = AutoProcessor.from_pretrained(model_name)
        self._model = AutoModel.from_pretrained(model_name, dtype=self._dtype)
        self._model.to(device)
        self._model.eval()

    @property
    def embedding_dim(self) -> int:
        return self._model.config.vision_config.hidden_size

    @torch.inference_mode()
    def embed_images(self, images_rgb: list[np.ndarray]) -> np.ndarray:
        """Embed a batch of RGB uint8 images; returns `(n, dim)` float16
        L2-normalized embeddings."""
        if not images_rgb:
            return np.zeros((0, self.embedding_dim), dtype=np.float16)

        pil_images = [Image.fromarray(img) for img in images_rgb]
        inputs = self._processor(images=pil_images, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self._device, dtype=self._dtype)

        features = self._model.get_image_features(pixel_values=pixel_values)
        features = features / features.norm(dim=-1, keepdim=True)
        return features.to(torch.float16).cpu().numpy()

    @torch.inference_mode()
    def embed_text(self, texts: list[str]) -> np.ndarray:
        """Embed a batch of text queries into the same space as
        `embed_images` — used for text-to-image search (P4), and for this
        module's own sanity check. Returns `(n, dim)` float16 L2-normalized.
        """
        if not texts:
            return np.zeros((0, self.embedding_dim), dtype=np.float16)

        inputs = self._processor(text=texts, padding="max_length", return_tensors="pt")
        input_ids = inputs["input_ids"].to(self._device)

        features = self._model.get_text_features(input_ids=input_ids)
        features = features / features.norm(dim=-1, keepdim=True)
        return features.to(torch.float16).cpu().numpy()
