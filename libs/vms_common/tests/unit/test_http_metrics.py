"""vms_http_request_seconds: one series per route template, status class, streams not buffered."""

import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from vms_common.http_metrics import HttpMetricsMiddleware, request_seconds


def _count(service, method, route, status):
    return request_seconds.labels(service, method, route, status)._sum.get() is not None and sum(
        b.get() for b in request_seconds.labels(service, method, route, status)._buckets
    )


def _app(service):
    app = FastAPI()
    app.add_middleware(HttpMetricsMiddleware, service=service)

    @app.get("/items/{item_id}")
    def item(item_id: int):
        if item_id == 13:
            raise HTTPException(status_code=404)
        return {"id": item_id}

    @app.get("/boom")
    def boom():
        raise RuntimeError("bug")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/stream")
    def stream():
        def gen():
            yield "a"
            yield "b"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def test_requests_are_counted_by_route_template_and_status_class():
    svc = "t-templates"
    client = TestClient(_app(svc), raise_server_exceptions=False)
    for i in (1, 2, 3):
        client.get(f"/items/{i}")  # three different ids, one series
    client.get("/items/13")  # a 404 raised by the handler
    client.get("/nowhere")  # no route matched
    assert _count(svc, "GET", "/items/{item_id}", "2xx") == 3
    assert _count(svc, "GET", "/items/{item_id}", "4xx") == 1
    assert _count(svc, "GET", "unmatched", "4xx") == 1


def test_an_unhandled_exception_is_a_5xx():
    svc = "t-boom"
    TestClient(_app(svc), raise_server_exceptions=False).get("/boom")
    assert _count(svc, "GET", "/boom", "5xx") == 1


def test_health_and_metrics_are_not_counted():
    svc = "t-health"
    TestClient(_app(svc)).get("/health")
    assert _count(svc, "GET", "/health", "2xx") == 0


def test_a_streamed_response_arrives_whole_and_is_counted_once():
    svc = "t-stream"
    r = TestClient(_app(svc)).get("/stream")
    assert r.text == "ab" and r.headers["content-type"].startswith("text/event-stream")
    assert _count(svc, "GET", "/stream", "2xx") == 1


def test_a_websocket_scope_passes_through():
    sent = []

    async def inner(scope, receive, send):
        sent.append(scope["type"])

    mw = HttpMetricsMiddleware(inner, service="t-ws")
    asyncio.run(mw({"type": "websocket", "path": "/ws"}, None, None))
    assert sent == ["websocket"]
