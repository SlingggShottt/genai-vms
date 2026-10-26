"""Cutting the part of a frame the operator drew a box around (P4-J1, design §10.1). Pure.

The box is a fraction of the frame, so the browser can draw it at any size. It is widened a little
on every side: a tight box around a person cuts off the edges the encoder uses to tell a person
from a pole, and a hand-drawn box is rarely tight anyway. A crop smaller than `MIN_SIDE_PX` after
widening is upscaled, because SigLIP resizes everything to 224 and a 20-pixel sliver is noise
whatever the scale; the contract already refuses boxes too small to mean anything."""

from __future__ import annotations

import io

from PIL import Image

PAD = 0.08  # of the box's own width and height
MIN_SIDE_PX = 48


def crop_jpeg(data: bytes, bbox: list[float]) -> bytes:
    """The box `[x0, y0, x1, y1]` (fractions of the frame) of the image in `data`, as JPEG.

    Raises OSError for bytes that are not an image (the caller answers 400)."""
    x0, y0, x1, y1 = bbox
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        width, height = image.size
        pad_x, pad_y = (x1 - x0) * PAD, (y1 - y0) * PAD
        left = max(0, int((x0 - pad_x) * width))
        top = max(0, int((y0 - pad_y) * height))
        right = min(width, max(left + 1, int((x1 + pad_x) * width + 0.5)))
        bottom = min(height, max(top + 1, int((y1 + pad_y) * height + 0.5)))
        piece = image.crop((left, top, right, bottom))
    short = min(piece.size)
    if short < MIN_SIDE_PX:
        scale = MIN_SIDE_PX / short
        piece = piece.resize((round(piece.width * scale), round(piece.height * scale)))
    out = io.BytesIO()
    piece.save(out, format="JPEG", quality=92)
    return out.getvalue()
