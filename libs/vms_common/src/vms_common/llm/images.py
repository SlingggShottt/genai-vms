"""Image caps for VLM calls. The 4 GB GPU cannot afford a 1080p frame times eight, so the
gateway — the one place every VLM call passes through — enforces the task's limits
(CLAUDE.md: "cap frames/pixels for VLM calls") instead of trusting each caller.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Sequence

from PIL import Image, UnidentifiedImageError

from vms_common.llm.errors import LLMRequestError
from vms_common.llm.types import ImageInput

JPEG_QUALITY = 85


def prepare_images(
    images: Sequence[ImageInput], *, max_images: int, max_edge: int
) -> list[ImageInput]:
    """Check the image count and shrink anything whose long edge exceeds `max_edge`.

    Images already within the cap are passed through byte-for-byte. CPU work: call it via
    `asyncio.to_thread` from async code.
    """
    if not images:
        raise LLMRequestError("vision() needs at least one image")
    if len(images) > max_images:
        raise LLMRequestError(
            f"{len(images)} images exceed this task's cap of {max_images} "
            "(max_images in config/models.yaml)"
        )
    return [_cap_edge(image, max_edge) for image in images]


def _cap_edge(image: ImageInput, max_edge: int) -> ImageInput:
    try:
        with Image.open(io.BytesIO(image.data)) as opened:
            width, height = opened.size  # header only: no decode yet
            if max(width, height) <= max_edge:
                return image
            scale = max_edge / max(width, height)
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            resized = opened.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise LLMRequestError(f"not a decodable image: {exc}") from exc
    buffer = io.BytesIO()
    resized.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return ImageInput(data=buffer.getvalue(), mime="image/jpeg")


def to_data_url(image: ImageInput) -> str:
    return f"data:{image.mime};base64,{base64.b64encode(image.data).decode('ascii')}"
