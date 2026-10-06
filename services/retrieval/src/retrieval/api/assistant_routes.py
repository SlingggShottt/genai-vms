"""HTTP surface of the assistant (design §9, §10.3). Internal like the rest of retrieval: the api
authenticates and passes `X-User-Id`; a session is only ever visible to the user who made it.
Messages stream as server-sent events: `tool_call`, `tool_result`, `token`, `citation`, `done`,
`error`."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from retrieval.assistant.agent import Assistant
from retrieval.assistant.starters import starters
from retrieval.assistant.store import ChatStore

router = APIRouter(prefix="/assistant", tags=["assistant"])


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


def _user(x_user_id: str | None) -> uuid.UUID:
    try:
        return uuid.UUID(x_user_id or "")
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing user") from exc


def _sid(session_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed session id") from exc


def _store(request: Request) -> ChatStore:
    return request.app.state.chat_store


def _session_json(row) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("/starters")
async def get_starters(request: Request) -> dict[str, list[str]]:
    return {"questions": await starters(request.app.state.sessions)}


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    request: Request, x_user_id: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    return _session_json(await _store(request).create(_user(x_user_id)))


@router.get("/sessions")
async def list_sessions(
    request: Request, x_user_id: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    rows = await _store(request).list(_user(x_user_id))
    return {"items": [_session_json(r) for r in rows]}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str, request: Request, x_user_id: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    store = _store(request)
    row = await store.get(_sid(session_id), _user(x_user_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    messages = await store.messages(row.id)
    return {
        **_session_json(row),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "citations": m.citations,
                "tools": m.tools,
                "status": m.status,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str, request: Request, x_user_id: Annotated[str | None, Header()] = None
) -> None:
    if not await _store(request).delete(_sid(session_id), _user(x_user_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


@router.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: str,
    body: MessageIn,
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    sid = _sid(session_id)
    if await _store(request).get(sid, _user(x_user_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    assistant: Assistant = request.app.state.assistant

    async def stream() -> AsyncIterator[str]:
        async for event in assistant.respond(sid, body.content.strip()):
            yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
