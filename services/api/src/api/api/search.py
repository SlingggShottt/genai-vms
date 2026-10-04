"""Search endpoints (P4-J4): the api authenticates, forwards to the retrieval service and turns
the s3:// uris in its answer into presigned urls made per request (CLAUDE.md: never store or
return a permanent link). Every role may search (design §9)."""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from pydantic import BaseModel
from vms_common.contracts.search import SearchRequest
from vms_db.models import User

from api.api.errors import APIError
from api.api.ratelimit import limit
from api.api.security import get_current_user

router = APIRouter(prefix="/search", tags=["search"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024


async def _presigned(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    s3 = request.app.state.s3

    async def url(uri: str | None) -> str | None:
        return await s3.presign_get(uri) if uri else None

    for r in payload.get("results", []):
        r["keyframe_url"] = await url(r.pop("keyframe_uri", None))
        r["crop_urls"] = [u for u in [await url(c) for c in r.pop("crop_uris", [])] if u]
    return payload


async def _forward(request: Request, user: User, path: str, **kwargs: Any) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(
            base_url=settings.retrieval_url, timeout=settings.search_timeout_seconds
        ) as client:
            response = await client.post(path, headers={"X-User-Id": str(user.id)}, **kwargs)
    except httpx.TimeoutException as exc:
        raise APIError(
            "UPSTREAM_TIMEOUT",
            "The search took too long. Try fast mode or a narrower question.",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        ) from exc
    except httpx.HTTPError as exc:
        raise APIError(
            "UPSTREAM_UNAVAILABLE",
            "Search is not available right now.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    if response.status_code == 400:
        raise APIError(
            "VALIDATION_ERROR",
            response.json().get("detail", "Bad request."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if response.status_code == 422:
        raise APIError(
            "VALIDATION_ERROR",
            "That search could not be understood.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if response.status_code >= 400:
        raise APIError(
            "UPSTREAM_UNAVAILABLE",
            "Search is not available right now.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return await _presigned(request, response.json())


@router.post("", dependencies=[Depends(limit("search"))])
async def search(
    body: SearchRequest, request: Request, user: Annotated[User, Depends(get_current_user)]
) -> dict[str, Any]:
    return await _forward(request, user, "/search", json=body.model_dump(mode="json"))


@router.post("/image", dependencies=[Depends(limit("search"))])
async def search_image(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
    cameras: Annotated[str, Form()] = "",
    top_k: Annotated[int, Form(ge=1, le=30)] = 12,
) -> dict[str, Any]:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise APIError(
            "VALIDATION_ERROR",
            "Send one image of at most 8 MB.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return await _forward(
        request,
        user,
        "/search/image",
        files={"file": (file.filename or "query.jpg", data, file.content_type or "image/jpeg")},
        data={"cameras": cameras, "top_k": str(top_k)},
    )


class GroundingIn(BaseModel):
    search_id: str
    result_id: str


@router.post("/grounding", dependencies=[Depends(limit("search"))])
async def grounding(
    body: GroundingIn, request: Request, user: Annotated[User, Depends(get_current_user)]
) -> dict[str, Any]:
    """Masks of the objects a search result matched, drawn over its keyframe by the UI."""
    settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(base_url=settings.retrieval_url, timeout=120.0) as client:
            response = await client.post("/search/grounding", json=body.model_dump())
    except httpx.HTTPError as exc:
        raise APIError(
            "UPSTREAM_UNAVAILABLE",
            "Object outlines are not available right now.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    if response.status_code == 404:
        raise APIError(
            "NOT_FOUND",
            "That result is no longer available; search again.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if response.status_code >= 400:
        raise APIError(
            "UPSTREAM_UNAVAILABLE",
            "Object outlines are not available right now.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return response.json()
