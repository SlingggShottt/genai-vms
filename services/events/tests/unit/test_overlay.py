"""Drawing the flagged boxes on a keyframe (P3-D4) — pure."""

from __future__ import annotations

from io import BytesIO

import pytest
from events.domain.evidence import EvidenceBox
from events.domain.overlay import draw_boxes
from PIL import Image, UnidentifiedImageError

BLUE = (0, 0, 255)


def jpeg(size: tuple[int, int] = (448, 252)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, BLUE).save(out, format="JPEG", quality=95)
    return out.getvalue()


def box(bbox: tuple[float, float, float, float], track: str = "t1") -> EvidenceBox:
    return EvidenceBox(track_id=track, category="person", bbox=bbox)


def decode(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGB")


def is_red(pixel: tuple[int, int, int]) -> bool:
    return pixel[0] > 200 and pixel[1] < 90 and pixel[2] < 90


def is_blue(pixel: tuple[int, int, int]) -> bool:
    return pixel[2] > 200 and pixel[0] < 60


def test_the_box_outline_is_drawn_where_it_is_and_nothing_else_is_touched() -> None:
    result = decode(draw_boxes(jpeg(), [box((0.25, 0.25, 0.75, 0.75))]))

    assert result.size == (448, 252)
    assert is_red(result.getpixel((112, 126))), "left edge, vertically centred"
    assert is_red(result.getpixel((224, 63))), "top edge, horizontally centred"
    assert is_blue(result.getpixel((224, 126))), "inside the box is left alone"
    assert is_blue(result.getpixel((10, 10))), "outside is left alone"


def test_every_box_is_drawn() -> None:
    result = decode(
        draw_boxes(jpeg(), [box((0.1, 0.1, 0.3, 0.5), "t1"), box((0.6, 0.2, 0.9, 0.8), "t2")])
    )

    assert is_red(result.getpixel((round(0.1 * 448), 126)))
    assert is_red(result.getpixel((round(0.9 * 448) - 1, 126)))


def test_no_boxes_is_the_same_picture() -> None:
    result = decode(draw_boxes(jpeg(), []))

    assert result.size == (448, 252)
    assert is_blue(result.getpixel((224, 126))) and is_blue(result.getpixel((0, 0)))


@pytest.mark.parametrize(
    ("size", "line_px"),
    [
        ((448, 252), 3),  # the model's own size: 3 px
        ((252, 448), 3),  # sized by the longer side, portrait or landscape
        ((1920, 1080), 13),  # so it is still ~3 px once the gateway shrinks it to 448
        ((100, 60), 2),  # but never thinner than 2 px
    ],
)
def test_the_line_is_about_three_pixels_thick_at_the_size_the_model_sees(
    size: tuple[int, int], line_px: int
) -> None:
    image = decode(draw_boxes(jpeg(size), [box((0.5, 0.2, 0.9, 0.8))]))
    y, x0 = image.height // 2, round(0.5 * image.width)
    thickness = sum(is_red(image.getpixel((x, y))) for x in range(max(0, x0 - 30), x0 + 30))
    assert thickness == line_px


def test_something_that_is_not_an_image_is_an_error_not_a_blank_frame() -> None:
    with pytest.raises(UnidentifiedImageError):
        draw_boxes(b"not a jpeg", [box((0.1, 0.1, 0.5, 0.5))])


def test_the_input_is_not_modified() -> None:
    original = jpeg()
    kept = bytes(original)
    draw_boxes(original, [box((0.1, 0.1, 0.5, 0.5))])
    assert original == kept
