"""Image caps for VLM calls."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image
from vms_common.llm.errors import LLMRequestError
from vms_common.llm.images import prepare_images, to_data_url
from vms_common.llm.types import ImageInput


def _image(width: int, height: int, fmt: str = "JPEG", mode: str = "RGB") -> ImageInput:
    buffer = io.BytesIO()
    Image.new(mode, (width, height), "red").save(buffer, format=fmt)
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]
    return ImageInput(data=buffer.getvalue(), mime=mime)  # type: ignore[arg-type]


def _size(image: ImageInput) -> tuple[int, int]:
    with Image.open(io.BytesIO(image.data)) as opened:
        return opened.size


def test_small_images_pass_through_byte_for_byte() -> None:
    original = _image(320, 240)
    (out,) = prepare_images([original], max_images=4, max_edge=448)
    assert out is original


def test_edge_of_exactly_the_cap_is_left_alone() -> None:
    original = _image(448, 252)
    (out,) = prepare_images([original], max_images=4, max_edge=448)
    assert out.data == original.data


def test_oversized_landscape_is_shrunk_to_the_long_edge_keeping_aspect_ratio() -> None:
    (out,) = prepare_images([_image(1920, 1080)], max_images=4, max_edge=448)
    assert _size(out) == (448, 252)
    assert out.mime == "image/jpeg"


def test_oversized_portrait_is_shrunk_by_its_height() -> None:
    (out,) = prepare_images([_image(1080, 1920)], max_images=4, max_edge=448)
    assert _size(out) == (252, 448)


def test_png_with_alpha_is_converted_when_it_has_to_shrink() -> None:
    (out,) = prepare_images([_image(900, 900, fmt="PNG", mode="RGBA")], max_images=1, max_edge=300)
    assert _size(out) == (300, 300)
    assert out.mime == "image/jpeg"


def test_degenerate_aspect_ratio_never_rounds_to_a_zero_side() -> None:
    (out,) = prepare_images([_image(4000, 3)], max_images=1, max_edge=100)
    assert _size(out) == (100, 1)


def test_more_images_than_the_cap_is_a_request_error() -> None:
    with pytest.raises(LLMRequestError, match="5 images exceed this task's cap of 4"):
        prepare_images([_image(10, 10)] * 5, max_images=4, max_edge=448)


def test_no_images_is_a_request_error() -> None:
    with pytest.raises(LLMRequestError, match="at least one image"):
        prepare_images([], max_images=4, max_edge=448)


@pytest.mark.parametrize("data", [b"", b"not an image", b"\xff\xd8\xff garbage"])
def test_undecodable_bytes_are_a_request_error_not_a_crash(data: bytes) -> None:
    with pytest.raises(LLMRequestError, match="not a decodable image"):
        prepare_images([ImageInput(data=data)], max_images=1, max_edge=448)


def test_data_url_round_trips_the_bytes_and_mime() -> None:
    image = _image(8, 8, fmt="PNG")
    url = to_data_url(image)
    header, _, payload = url.partition(",")
    assert header == "data:image/png;base64"
    assert base64.b64decode(payload) == image.data
