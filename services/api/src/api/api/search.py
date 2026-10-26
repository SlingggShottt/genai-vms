"""Search endpoints (P4-J4): the api authenticates, forwards to the retrieval service and turns
the s3:// uris in its answer into presigned urls made per request (CLAUDE.md: never store or
return a permanent link). Every role may search (design §9)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from vms_common.contracts.search import CropSearchRequest, SearchFilters, SearchRequest
from vms_db.models import Event, User

from api.api.deps import SessionDep
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


async def _forward(
    request: Request, user: User, path: str, *, method: str = "POST", **kwargs: Any
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(
            base_url=settings.retrieval_url, timeout=settings.search_timeout_seconds
        ) as client:
            response = await client.request(
                method, path, headers={"X-User-Id": str(user.id)}, **kwargs
            )
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
    if response.status_code == 404:  # the frame to search from is gone (retention, an old search)
        raise APIError(
            "NOT_FOUND",
            response.json().get("detail", "Not found."),
            status_code=status.HTTP_404_NOT_FOUND,
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


@router.get("/frame", dependencies=[Depends(limit("search"))])
async def search_frame(
    camera_id: str,
    at: AwareDatetime,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """The stored frame nearest a moment of a camera, as a picture to draw a "find similar" box
    on while a recording is paused. `at` in the answer is when that frame was taken: send it back
    to `/search/image/crop` so the box lands on the frame it was drawn on."""
    found = await _forward(
        request,
        user,
        "/search/frame",
        method="GET",
        params={"camera_id": camera_id, "at": at.isoformat()},
    )
    url = await request.app.state.s3.presign_get(found["keyframe_uri"])
    return {"url": url, "at": found["at"], "camera_id": camera_id}


class CropSearchIn(BaseModel):
    """ "Find similar" on a box drawn over a frame the browser is showing. The browser never holds a
    storage uri, so the frame is named the way the browser knows it: an event and which of its
    keyframes, a result of a recent search, or a camera and a moment (a paused recording)."""

    bbox: list[float]
    event_id: str | None = None
    keyframe_index: int = Field(default=0, ge=0, le=15)
    search_id: str | None = None
    result_id: str | None = None
    camera_id: str | None = None
    at: AwareDatetime | None = None
    cameras: list[str] = Field(default_factory=list)
    top_k: int = Field(default=12, ge=1, le=30)


def _bad(message: str) -> APIError:
    return APIError("VALIDATION_ERROR", message, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/image/crop", dependencies=[Depends(limit("search"))])
async def search_image_crop(
    body: CropSearchIn,
    request: Request,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Images like the part of a frame inside the box: other tracks that look like it."""
    keyframe_uri = None
    if body.event_id is not None:
        if body.search_id or body.result_id or body.camera_id or body.at:
            raise _bad("Name the frame one way: an event, a search result, or a camera and time.")
        try:
            event = await session.get(Event, uuid.UUID(body.event_id))
        except ValueError as exc:
            raise _bad("Malformed event id.") from exc
        if event is None or body.keyframe_index >= len(event.keyframe_uris):
            raise APIError(
                "NOT_FOUND",
                "That event has no such keyframe.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        keyframe_uri = event.keyframe_uris[body.keyframe_index]
    try:
        forwarded = CropSearchRequest(
            bbox=body.bbox,
            keyframe_uri=keyframe_uri,
            search_id=body.search_id,
            result_id=body.result_id,
            camera_id=body.camera_id,
            at=body.at,
            filters=SearchFilters(cameras=body.cameras),
            top_k=body.top_k,
        )
    except ValidationError as exc:
        raise _bad(str(exc.errors()[0]["msg"]).removeprefix("Value error, ")) from exc
    return await _forward(request, user, "/search/crop", json=forwarded.model_dump(mode="json"))


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
