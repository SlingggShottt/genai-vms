"""Request-id middleware — generates/propagates `X-Request-ID`, binds it to
structlog context for the request's lifetime (NFR-OBS-01: correlation ids
in every log line) and clears context afterward.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from vms_common.logging import bind_context, clear_context

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        bind_context(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            clear_context()
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Headers every api response should carry (NFR-SEC, P7-J5). No `Content-Security-Policy`
    here: the api serves JSON, and the page's policy belongs to whatever serves the page."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # Tokens and personal data must not sit in a shared cache; a handler that sets its own
        # policy (an HLS playlist, say) keeps it.
        response.headers.setdefault("Cache-Control", "no-store")
        return response
