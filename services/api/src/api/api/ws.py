"""`WS /api/v1/ws?token=<access token>` — the live channel (P3-J3, design_architecture.md §9).

Server -> client only: JSON envelopes `{"type", "data", "ts"}` (`api/realtime/messages.py`), of
which a connection gets the types its role may see (`api.domain.alerts.WS_MESSAGE_ROLES`).
Anything the client sends is read and ignored.

The access token is a query parameter because browsers cannot set headers on a WebSocket. It
is short-lived and the connection ends when it does, so what ends up in an access log is
useless within minutes. The role is the user's *current* role (re-read at connect, as every
HTTP request does), and a deactivated user is refused.

The socket is accepted first and then closed with an application code, because a browser cannot
read the HTTP status of a refused handshake:

    4401  token missing/invalid/expired, or the user is gone — refresh the token, reconnect
    1013  this client fell too far behind — reconnect and refetch what it missed
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid

from fastapi import APIRouter, Query, WebSocket
from vms_common.auth import InvalidTokenError, decode_access_token
from vms_common.logging import get_logger
from vms_db.session import session_scope

from api.adapters.users import get_user_by_id
from api.realtime.hub import ConnectionHub, Subscriber

log = get_logger(__name__)

router = APIRouter(tags=["realtime"])

CLOSE_UNAUTHENTICATED = 4401
CLOSE_TOO_SLOW = 1013


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(RuntimeError, OSError):  # already closed by the peer
        await websocket.close(code=code, reason=reason)


async def _authenticate(websocket: WebSocket, token: str | None) -> tuple[str, str, float] | None:
    """`(user id, role, token expiry as a unix time)`, or `None` after closing the socket."""
    settings = websocket.app.state.settings
    if not token:
        await _close(websocket, CLOSE_UNAUTHENTICATED, "missing token")
        return None
    try:
        payload = decode_access_token(
            token, secret=settings.jwt.secret, algorithm=settings.jwt.algorithm
        )
        user_id = uuid.UUID(payload["sub"])
        expires_at = float(payload["exp"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        await _close(websocket, CLOSE_UNAUTHENTICATED, "invalid or expired token")
        return None
    async with session_scope(websocket.app.state.db_session_factory) as session:
        user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        await _close(websocket, CLOSE_UNAUTHENTICATED, "unknown or inactive user")
        return None
    return str(user.id), user.role.value, expires_at


def _retrieve_exception(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


async def _send_loop(websocket: WebSocket, subscriber: Subscriber) -> None:
    while True:
        await websocket.send_text(await subscriber.queue.get())


async def _read_and_ignore(websocket: WebSocket) -> None:
    while True:
        await websocket.receive_text()  # raises WebSocketDisconnect when the client leaves


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    await websocket.accept()
    identity = await _authenticate(websocket, token)
    if identity is None:
        return
    user_id, role, expires_at = identity

    hub: ConnectionHub = websocket.app.state.hub
    subscriber = hub.connect(role)
    log.info("ws_connected", user_id=user_id, role=role, connections=hub.connection_count)

    sender = asyncio.create_task(_send_loop(websocket, subscriber))
    reader = asyncio.create_task(_read_and_ignore(websocket))
    expiry = asyncio.create_task(asyncio.sleep(max(0.0, expires_at - time.time())))
    overflow = asyncio.create_task(subscriber.overflowed.wait())
    tasks = (sender, reader, expiry, overflow)
    for task in tasks:
        task.add_done_callback(_retrieve_exception)  # never "exception was never retrieved"
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if expiry in done:
            await _close(websocket, CLOSE_UNAUTHENTICATED, "token expired")
        elif overflow in done:
            await _close(websocket, CLOSE_TOO_SLOW, "client too slow")
    finally:
        # All synchronous, on purpose. Under a cancelling server (uvicorn on shutdown, a test
        # client closing the socket) every `await` here may itself be cancelled, so cleanup
        # placed after one could be skipped — leaving the subscriber for ever — and awaiting the
        # children keeps the handler alive a few loop turns longer. They finish by themselves
        # once cancelled; `_retrieve_exception` keeps them quiet.
        hub.disconnect(subscriber)
        for task in tasks:
            task.cancel()
        log.info("ws_disconnected", user_id=user_id, connections=hub.connection_count)
