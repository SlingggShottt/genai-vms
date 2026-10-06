"""HTTP surface of retrieval. Internal: the api authenticates the user and forwards (design §9);
`X-User-Id` rides along only so the search log knows who asked."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from vms_common.contracts.search import SearchFilters, SearchRequest, SearchResponse

from retrieval.grounding_service import GroundingRequest
from retrieval.pipeline import SearchPipeline

router = APIRouter()

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _pipeline(request: Request) -> SearchPipeline:
    return request.app.state.pipeline


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/ready")
async def ready(request: Request) -> dict[str, object]:
    loaded = request.app.state.encoder.loaded
    if not loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the SigLIP encoder is loading")
    return {"status": "ready", "profile": request.app.state.profile}


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
) -> SearchResponse:
    return await _pipeline(request).text(body, user_id=x_user_id)


@router.post("/search/image", response_model=SearchResponse)
async def search_image(
    request: Request,
    file: Annotated[UploadFile, File()],
    cameras: Annotated[str, Form()] = "",
    start: Annotated[datetime | None, Form()] = None,
    end: Annotated[datetime | None, Form()] = None,
    top_k: Annotated[int, Form(ge=1, le=30)] = 12,
    x_user_id: Annotated[str | None, Header()] = None,
) -> SearchResponse:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "send one image of at most 8 MB")
    try:
        filters = SearchFilters(
            cameras=[c for c in cameras.split(",") if c.strip()], start=start, end=end
        )
        return await _pipeline(request).image(
            data,
            filters=filters,
            top_k=top_k,
            label=file.filename or "uploaded image",
            user_id=x_user_id,
        )
    except OSError as exc:  # PIL: not an image
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "that file is not a readable image"
        ) from exc


@router.get("/incidents/{incident_id}/similar")
async def similar_incidents(incident_id: str, request: Request) -> dict[str, list[dict]]:
    """Written incidents closest to this one (by meaning and wording of their reports)."""
    brief = await request.app.state.pipeline.catalog.incident_brief(incident_id)
    if brief is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
    knowledge = request.app.state.knowledge
    if not knowledge.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the text embedder is loading")
    items = await knowledge.similar_incidents(
        incident_id, brief["title"], brief["summary"], brief["event_type"]
    )
    return {"items": items}


class GroundingIn(BaseModel):
    search_id: str
    result_id: str


@router.post("/search/grounding")
async def grounding(body: GroundingIn, request: Request) -> dict:
    """Masks of the objects a result matched (SAM 2.1-tiny), for the overlay on its keyframe."""
    recent = request.app.state.pipeline.recent.get((body.search_id, body.result_id))
    if recent is None or not recent[0]:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "that result is no longer available; search again"
        )
    keyframe_uri, segment_ids, track_ids = recent
    return await request.app.state.grounding.masks(
        GroundingRequest(keyframe_uri, segment_ids, track_ids)
    )
