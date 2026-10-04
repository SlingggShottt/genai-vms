"""Draws the flagged objects' boxes on a keyframe for the VLM (design §7.4: "bbox of involved
tracks drawn as coloured boxes") — JPEG bytes in, JPEG bytes out, no I/O.

The gateway shrinks every image to the task's `max_image_edge` (448 px) before the model sees it,
so the line is drawn about 3 px thick *at that size*: a fixed 3 px line on a 1920 px frame would
come out under a pixel thick and the model would not see the boxes it is asked about.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

from PIL import Image, ImageDraw

from events.domain.evidence import EvidenceBox

BOX_COLOUR = (255, 48, 48)
LINE_PX_AT_MODEL_SIZE = 3
MODEL_EDGE_PX = 448
JPEG_QUALITY = 88


def draw_boxes(jpeg: bytes, boxes: Sequence[EvidenceBox]) -> bytes:
    """`jpeg` with a coloured rectangle round each of `boxes` (normalized coordinates).
    Raises `PIL.UnidentifiedImageError` (an `OSError`) when the bytes are not an image."""
    with Image.open(BytesIO(jpeg)) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    line = max(2, round(max(width, height) * LINE_PX_AT_MODEL_SIZE / MODEL_EDGE_PX))
    draw = ImageDraw.Draw(image)
    for box in boxes:
        x1, y1, x2, y2 = box.bbox
        draw.rectangle(
            (x1 * width, y1 * height, x2 * width, y2 * height), outline=BOX_COLOUR, width=line
        )
    out = BytesIO()
    # 4:4:4, or JPEG smears a thin red line into its background and the box loses its colour
    image.save(out, format="JPEG", quality=JPEG_QUALITY, subsampling=0)
    return out.getvalue()
