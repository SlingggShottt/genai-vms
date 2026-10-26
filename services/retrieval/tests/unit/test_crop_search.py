"""P4-J1: "find similar" on a box drawn over a stored frame. Fakes only."""

from __future__ import annotations

import io
import types
from datetime import UTC, datetime

import pytest
from PIL import Image
from retrieval.adapters.frames import FrameNotAllowedError, FrameReader, check_keyframe_uri
from retrieval.domain.crop import MIN_SIDE_PX, crop_jpeg
from retrieval.pipeline import FrameUnavailableError, SearchPipeline
from retrieval.settings import RetrievalSettings
from vms_common.contracts.search import CropSearchRequest, SearchFilters

# ---- the pure cut ---------------------------------------------------------------------------


def two_colour_jpeg(width: int = 200, height: int = 100) -> bytes:
    """Left half red, right half blue."""
    image = Image.new("RGB", (width, height), (255, 0, 0))
    image.paste((0, 0, 255), (width // 2, 0, width, height))
    out = io.BytesIO()
    image.save(out, format="PNG")  # lossless: colours stay what they were drawn
    return out.getvalue()


def decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def test_the_box_is_cut_out_of_the_frame_with_a_margin() -> None:
    piece = decode(crop_jpeg(two_colour_jpeg(), [0.6, 0.2, 0.9, 0.8]))

    # 0.3 x 0.6 of 200 x 100 is 60 x 60 px; 8 % of the box is added on every side: 70 x 70
    assert piece.size == (70, 70)
    r, g, b = piece.getpixel((piece.width // 2, piece.height // 2))
    assert b > 200 and r < 60 and g < 60  # the right half, which is blue


def test_a_box_at_the_edge_is_clamped_to_the_frame_not_an_error() -> None:
    piece = decode(crop_jpeg(two_colour_jpeg(), [0.0, 0.0, 0.5, 0.5]))
    assert piece.size == (108, 54)  # the box and its margin on the sides that have room
    r, g, b = piece.getpixel((0, 0))
    assert r > 200 and g < 60 and b < 60  # red from the first pixel: nothing filled in outside


def test_a_tiny_box_is_scaled_up_so_the_encoder_has_something_to_look_at() -> None:
    piece = decode(crop_jpeg(two_colour_jpeg(1000, 800), [0.5, 0.5, 0.53, 0.53]))  # ~30 x 24 px
    assert min(piece.size) >= MIN_SIDE_PX


def test_bytes_that_are_not_an_image_are_an_oserror_for_the_route_to_answer() -> None:
    with pytest.raises(OSError):
        crop_jpeg(b"not an image", [0.1, 0.1, 0.5, 0.5])


# ---- which frames may be read ---------------------------------------------------------------


@pytest.mark.parametrize(
    "uri", ["s3://vms-keyframes/cam02/a.jpg", "s3://vms-keyframes/cam02/ev/0.jpg"]
)
def test_a_stored_keyframe_may_be_read(uri: str) -> None:
    assert check_keyframe_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "s3://vms-models/tg/v1/adapter_model.safetensors",
        "s3://vms-recordings/cam02/seg.mp4",
        "s3://vms-keyframes/",
        "s3://vms-keyframes",
        "s3://vms-keyframes/../vms-models/x",
        "https://example.com/a.jpg",
        "vms-keyframes/cam02/a.jpg",
        "",
    ],
)
def test_nothing_else_may_be_read_however_it_is_named(uri: str) -> None:
    with pytest.raises(FrameNotAllowedError):
        check_keyframe_uri(uri)


async def test_the_reader_checks_before_it_touches_storage() -> None:
    touched = []

    class S3:
        async def get_bytes(self, uri: str) -> bytes:
            touched.append(uri)
            return b""

    with pytest.raises(FrameNotAllowedError):
        await FrameReader(S3()).read("s3://vms-models/x")  # type: ignore[arg-type]
    assert touched == []


# ---- the pipeline step ----------------------------------------------------------------------

AT = datetime(2026, 10, 25, 9, 30, 15, tzinfo=UTC)


class FakeFrames:
    def __init__(self, data: bytes | None = None, *, fail: bool = False) -> None:
        self.data = data or two_colour_jpeg()
        self.fail = fail
        self.read_uris: list[str] = []

    async def read(self, uri: str) -> bytes:
        self.read_uris.append(uri)
        check_keyframe_uri(uri)
        if self.fail:
            raise ConnectionError("storage is down")
        return self.data


class FakeVectors:
    def __init__(self, uri: str | None, taken_ms: int | None = None) -> None:
        self.uri = uri
        self.taken_ms = taken_ms
        self.asked: list[tuple[str, int, float]] = []

    async def nearest_frame(self, camera: str, ts_ms: int, *, within_s: float = 4.0):  # noqa: ANN201
        self.asked.append((camera, ts_ms, within_s))
        if self.uri is None:
            return None
        return self.uri, self.taken_ms if self.taken_ms is not None else ts_ms


def pipeline(frames=None, vectors=None) -> tuple[SearchPipeline, list[dict]]:  # noqa: ANN001
    p = SearchPipeline(
        settings=RetrievalSettings(),
        encoder=None,  # type: ignore[arg-type]
        vectors=vectors,  # type: ignore[arg-type]
        catalog=None,  # type: ignore[arg-type]
        twins=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        profile="local",
        frames=frames,
    )
    calls: list[dict] = []

    async def image(data, *, filters, top_k, label, user_id=None):  # noqa: ANN001, ANN202
        calls.append(
            {"data": data, "filters": filters, "top_k": top_k, "label": label, "user": user_id}
        )
        return types.SimpleNamespace(kind="image")

    p.image = image  # type: ignore[method-assign]
    return p, calls


BOX = [0.6, 0.2, 0.9, 0.8]


async def test_a_named_keyframe_is_cut_and_searched_like_an_uploaded_image() -> None:
    frames = FakeFrames()
    p, calls = pipeline(frames)
    filters = SearchFilters(cameras=["cam02"])
    req = CropSearchRequest(
        bbox=BOX, keyframe_uri="s3://vms-keyframes/cam02/a.jpg", filters=filters, top_k=7
    )

    await p.crop(req, user_id="u1")

    assert frames.read_uris == ["s3://vms-keyframes/cam02/a.jpg"]
    (call,) = calls
    assert (call["filters"], call["top_k"], call["user"]) == (filters, 7, "u1")
    sent = decode(call["data"])
    assert sent.width < 200 and sent.height < 100  # a piece, not the whole frame
    r, _, b = sent.getpixel((sent.width // 2, sent.height // 2))
    assert b > 200 and r < 60


async def test_a_result_of_a_recent_search_names_its_keyframe() -> None:
    frames = FakeFrames()
    p, calls = pipeline(frames)
    p.recent[("s1", "r1")] = ("s3://vms-keyframes/cam03/b.jpg", [], [])

    await p.crop(CropSearchRequest(bbox=BOX, search_id="s1", result_id="r1"))

    assert frames.read_uris == ["s3://vms-keyframes/cam03/b.jpg"]
    assert calls[0]["label"] == "part of a result"


@pytest.mark.parametrize("recent", [None, (None, [], [])])
async def test_a_result_that_expired_or_had_no_keyframe_is_unavailable(recent) -> None:  # noqa: ANN001
    p, calls = pipeline(FakeFrames())
    if recent is not None:
        p.recent[("s1", "r1")] = recent
    with pytest.raises(FrameUnavailableError, match="no longer available"):
        await p.crop(CropSearchRequest(bbox=BOX, search_id="s1", result_id="r1"))
    assert calls == []


async def test_a_moment_on_a_camera_finds_the_nearest_stored_keyframe() -> None:
    vectors = FakeVectors("s3://vms-keyframes/cam02/near.jpg")
    frames = FakeFrames()
    p, calls = pipeline(frames, vectors)
    p._s = RetrievalSettings(crop_frame_window_s=9.0)

    await p.crop(CropSearchRequest(bbox=BOX, camera_id="cam02", at=AT))

    assert vectors.asked == [("cam02", int(AT.timestamp() * 1000), 9.0)]
    assert frames.read_uris == ["s3://vms-keyframes/cam02/near.jpg"]
    assert calls[0]["label"] == "part of cam02 at 15:00:15"  # the site's clock (IST), not UTC


async def test_the_search_is_labelled_with_when_the_frame_was_taken_not_when_it_was_asked_for() -> (
    None
):
    taken = AT.replace(second=19)
    vectors = FakeVectors("s3://vms-keyframes/cam02/near.jpg", int(taken.timestamp() * 1000))
    p, calls = pipeline(FakeFrames(), vectors)

    await p.crop(CropSearchRequest(bbox=BOX, camera_id="cam02", at=AT))

    assert calls[0]["label"] == "part of cam02 at 15:00:19"


async def test_frame_near_says_which_frame_and_when_so_a_box_can_be_sent_back_to_it() -> None:
    taken = AT.replace(second=19)
    vectors = FakeVectors("s3://vms-keyframes/cam02/near.jpg", int(taken.timestamp() * 1000))
    p, _ = pipeline(FakeFrames(), vectors)

    uri, when = await p.frame_near("cam02", AT)

    assert (uri, when) == ("s3://vms-keyframes/cam02/near.jpg", taken)


async def test_no_stored_frame_near_the_moment_is_unavailable() -> None:
    p, calls = pipeline(FakeFrames(), FakeVectors(None))
    with pytest.raises(FrameUnavailableError, match="close to that moment"):
        await p.crop(CropSearchRequest(bbox=BOX, camera_id="cam02", at=AT))
    assert calls == []


async def test_a_uri_outside_the_keyframes_bucket_is_refused_not_unavailable() -> None:
    p, calls = pipeline(FakeFrames())
    with pytest.raises(FrameNotAllowedError):
        await p.crop(CropSearchRequest(bbox=BOX, keyframe_uri="s3://vms-models/tg/v1/x"))
    assert calls == []


async def test_storage_that_fails_is_a_frame_that_is_unavailable() -> None:
    p, calls = pipeline(FakeFrames(fail=True))
    with pytest.raises(FrameUnavailableError, match="no longer available"):
        await p.crop(CropSearchRequest(bbox=BOX, keyframe_uri="s3://vms-keyframes/a.jpg"))
    assert calls == []


async def test_without_a_frame_reader_it_says_so() -> None:
    p, _ = pipeline(None)
    with pytest.raises(FrameUnavailableError):
        await p.crop(CropSearchRequest(bbox=BOX, keyframe_uri="s3://vms-keyframes/a.jpg"))
