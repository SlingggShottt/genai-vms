"""Sanity test for perception.adapters.embedder (P2-D5 AC): a text query
ranks the matching-colour image crop above the others in a small fixture
set. Needs a GPU + downloads `google/siglip2-base-patch16-224` from
Hugging Face on first run (cached after) — marked `integration`, not part
of the default `make test`.

Verified for real (not just asserted): on an RTX 3050, "a red car" /
"a blue car" / "a green car" against solid red/blue/green crops gives a
clean diagonal — each text query's top match is its own colour, with the
correct match scoring 4-6x higher than the next best (see
`adapters/embedder.py`'s module docstring for the actual numbers this
test's assertions are loosely based on).
"""

from __future__ import annotations

import numpy as np
import pytest
from perception.adapters.embedder import SiglipEmbedder

pytestmark = pytest.mark.integration


def _solid_crop(rgb: tuple[int, int, int], *, h: int = 224, w: int = 224) -> np.ndarray:
    crop = np.zeros((h, w, 3), dtype=np.uint8)
    crop[:, :] = rgb
    return crop


def test_text_query_ranks_matching_colour_crop_highest() -> None:
    embedder = SiglipEmbedder(device="cuda:0")

    crops = {
        "red": _solid_crop((200, 30, 30)),
        "blue": _solid_crop((30, 60, 200)),
        "green": _solid_crop((40, 160, 60)),
    }
    colors = list(crops.keys())
    image_vectors = embedder.embed_images([crops[c] for c in colors])
    text_vectors = embedder.embed_text([f"a {c} car" for c in colors])

    similarities = image_vectors.astype(np.float32) @ text_vectors.astype(np.float32).T

    for query_idx, color in enumerate(colors):
        best_image_idx = int(np.argmax(similarities[:, query_idx]))
        assert colors[best_image_idx] == color, (
            f"'a {color} car' should rank the {color} crop highest, "
            f"got {colors[best_image_idx]} (similarities: {similarities[:, query_idx]})"
        )
