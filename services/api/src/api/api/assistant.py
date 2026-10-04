"""Assistant endpoints (design §9): sessions and a streamed conversation, proxied to the
retrieval service where the agent runs. The api authenticates and passes `X-User-Id`; retrieval
only ever shows a session to the user who made it. The message endpoint relays the server-sent
events byte for byte, and closing the browser's request closes the upstream one, which retrieval
records as a stopped answer."""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from vms_db.models import User

from api.api.errors import APIError
from api.api.ratelimit import limit
from api.api.security import get_current_user

router = APIRouter(prefix="/assistant", tags=["assistant"])


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


def _unavailable() -> APIError:
    return APIError(
        "UPSTREAM_UNAVAILABLE",
        "The assistant is not available right now.",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _check(response: httpx.Response) -> None:
    if response.status_code == 404:
        raise APIError(
            "NOT_FOUND", "Conversation not found.", status_code=status.HTTP_404_NOT_FOUND
        )
    if response.status_code >= 400:
        raise _unavailable()


async def _json(
    request: Request, user: User, method: str, path: str, **kwargs: Any
) -> httpx.Response:
    settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(base_url=settings.retrieval_url, timeout=30.0) as client:
            response = await client.request(
                method, path, headers={"X-User-Id": str(user.id)}, **kwargs
            )
    except httpx.HTTPError as exc:
        raise _unavailable() from exc
    _check(response)
    return response


@router.get("/starters")
async def starters(request: Request, user: Annotated[User, Depends(get_current_user)]) -> Any:
    return (await _json(request, user, "GET", "/assistant/starters")).json()


@router.get("/sessions")
async def list_sessions(request: Request, user: Annotated[User, Depends(get_current_user)]) -> Any:
    return (await _json(request, user, "GET", "/assistant/sessions")).json()


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(request: Request, user: Annotated[User, Depends(get_current_user)]) -> Any:
    return (await _json(request, user, "POST", "/assistant/sessions")).json()


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str, request: Request, user: Annotated[User, Depends(get_current_user)]
) -> Any:
    return (await _json(request, user, "GET", f"/assistant/sessions/{session_id}")).json()


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str, request: Request, user: Annotated[User, Depends(get_current_user)]
) -> None:
    await _json(request, user, "DELETE", f"/assistant/sessions/{session_id}")


@router.post("/sessions/{session_id}/messages", dependencies=[Depends(limit("assistant"))])
async def post_message(
    session_id: str,
    body: MessageIn,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    settings = request.app.state.settings
    client = httpx.AsyncClient(
        base_url=settings.retrieval_url, timeout=httpx.Timeout(300.0, connect=5.0)
    )
    try:
        upstream = await client.send(
            client.build_request(
                "POST",
                f"/assistant/sessions/{session_id}/messages",
                json=body.model_dump(),
                headers={"X-User-Id": str(user.id)},
            ),
            stream=True,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        raise _unavailable() from exc
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        _check(upstream)

    async def relay():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
