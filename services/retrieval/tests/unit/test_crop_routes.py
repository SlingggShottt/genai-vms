"""The retrieval service's two "find similar" routes, over the real FastAPI app with the pipeline
replaced by a recorder (P4-J1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from retrieval.adapters.frames import FrameNotAllowedError
from retrieval.api.routes import router
from retrieval.pipeline import FrameUnavailableError

TAKEN = datetime(2026, 10, 25, 9, 30, 19, tzinfo=UTC)


class FakePipeline:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.crops: list[tuple] = []

    async def crop(self, req, *, user_id=None):  # noqa: ANN001, ANN201
        if self.error:
            raise self.error
        self.crops.append((req, user_id))
        return {
            "search_id": "s", "query": "part of a frame", "mode": "fast", "kind": "image",
            "profile": "local", "plan": None, "results": [], "timings_ms": {}, "notes": [],
        }  # fmt: skip

    async def frame_near(self, camera_id, at):  # noqa: ANN001, ANN201
        if self.error:
            raise self.error
        return "s3://vms-keyframes/cam02/near.jpg", TAKEN


def client(pipeline: FakePipeline) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.pipeline = pipeline
    app.state.profile = "local"
    return TestClient(app)


BODY = {"bbox": [0.1, 0.1, 0.5, 0.6], "keyframe_uri": "s3://vms-keyframes/cam02/a.jpg"}


def test_a_crop_request_reaches_the_pipeline_with_the_user_it_is_for() -> None:
    pipeline = FakePipeline()
    response = client(pipeline).post("/search/crop", json=BODY, headers={"X-User-Id": "u1"})

    assert response.status_code == 200 and response.json()["kind"] == "image"
    ((req, user),) = pipeline.crops
    assert req.keyframe_uri == "s3://vms-keyframes/cam02/a.jpg" and user == "u1"


@pytest.mark.parametrize(
    "error,status",
    [
        (FrameNotAllowedError("that is not a stored keyframe"), 400),
        (FrameUnavailableError("that result is no longer available; search again"), 404),
        (OSError("cannot identify image file"), 404),
    ],
)
def test_a_frame_that_cannot_be_used_is_a_400_or_404_with_the_reason(
    error: Exception, status: int
) -> None:
    response = client(FakePipeline(error)).post("/search/crop", json=BODY)
    assert response.status_code == status and response.json()["detail"]


def test_a_box_that_is_not_one_is_a_422_before_the_pipeline_is_touched() -> None:
    pipeline = FakePipeline()
    response = client(pipeline).post("/search/crop", json={**BODY, "bbox": [0.5, 0.5, 0.5, 0.5]})
    assert response.status_code == 422 and pipeline.crops == []


def test_the_frame_lookup_returns_the_uri_and_when_it_was_taken() -> None:
    response = client(FakePipeline()).get(
        "/search/frame", params={"camera_id": "cam02", "at": "2026-10-25T09:30:15+00:00"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "keyframe_uri": "s3://vms-keyframes/cam02/near.jpg",
        "at": TAKEN.isoformat(),
    }


def test_the_frame_lookup_needs_a_time_zone_and_reports_a_missing_frame() -> None:
    naive = client(FakePipeline()).get(
        "/search/frame", params={"camera_id": "cam02", "at": "2026-10-25T09:30:15"}
    )
    assert naive.status_code == 400

    gone = client(FakePipeline(FrameUnavailableError("no stored frame of that camera"))).get(
        "/search/frame", params={"camera_id": "cam02", "at": "2026-10-25T09:30:15+00:00"}
    )
    assert gone.status_code == 404 and "no stored frame" in gone.json()["detail"]
