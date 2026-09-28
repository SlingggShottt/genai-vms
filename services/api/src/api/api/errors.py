"""API error envelope and exception handlers (docs/style_guide.md §A.5):

    { "error": { "code": "...", "message": "...", "details": {}, "request_id": "..." } }

Raise `APIError` from domain/adapters code for a specific status + machine
code; anything else is caught by the catch-all handler and reported as a
generic 500 without leaking internals.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from vms_common.logging import get_logger

log = get_logger(__name__)

_CODE_BY_STATUS = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "UNPROCESSABLE",
    429: "RATE_LIMITED",
    503: "DEPENDENCY_UNAVAILABLE",
}


class APIError(Exception):
    """Raise for a specific error envelope: status code + machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build the envelope response, stamping `X-Request-ID` on the response
    itself rather than relying solely on `RequestIDMiddleware` — a response
    built by an exception handler doesn't reliably get its headers mutated by
    that middleware's post-`call_next` step (BaseHTTPMiddleware quirk).
    """
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
            }
        },
        headers={"X-Request-ID": request_id} if request_id else None,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler so all errors — expected or not — return the envelope."""

    @app.exception_handler(APIError)
    async def _api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return _error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "Request validation failed.",
            {"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _CODE_BY_STATUS.get(exc.status_code, "HTTP_ERROR")
        return _error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", request_id=_request_id(request), error=str(exc))
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "An unexpected error occurred.",
        )
