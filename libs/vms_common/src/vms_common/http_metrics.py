"""`vms_http_request_seconds{service,method,route,status}`: how long the HTTP API takes, by route.

A plain ASGI middleware, not Starlette's `BaseHTTPMiddleware`, because that one buffers a streamed
response and the assistant answers over server-sent events. `route` is the route *template*
(`/incidents/{incident_id}`), so the number of series stays small; a request that matched no route
is `unmatched`. `status` is the class (`2xx` ... `5xx`). The time covers the whole response, so a
streamed answer counts until its last byte. `/metrics`, `/health` and `/ready` are not counted.
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vms_common.metrics import histogram

request_seconds = histogram(
    "http",
    "request",
    "seconds",
    "Time to answer an HTTP request",
    ("service", "method", "route", "status"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 120.0),
)
UNCOUNTED = frozenset({"/metrics", "/health", "/ready"})


class HttpMetricsMiddleware:
    def __init__(self, app: ASGIApp, service: str) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in UNCOUNTED:
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500  # an exception before the response starts is a 500

        async def send_and_note(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        finally:
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            request_seconds.labels(
                service=self.service,
                method=scope["method"],
                route=route,
                status=f"{status // 100}xx",
            ).observe(time.perf_counter() - started)
