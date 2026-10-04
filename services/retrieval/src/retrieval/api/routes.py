"""HTTP surface of retrieval. Internal: the api authenticates the user and forwards (design §9);
`X-User-Id` rides along only so the search log knows who asked."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile, status
from vms_common.contracts.search import SearchFilters, SearchRequest, SearchResponse

from retrieval.pipeline import SearchPipeline

router = APIRouter()

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _pipeline(request: Request) -> SearchPipeline:
    return request.app.state.pipeline


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
