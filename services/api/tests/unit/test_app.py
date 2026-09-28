"""Unit tests for the api app factory: error envelope shape, request-id
middleware, and /health, /ready with an unreachable database
(P1-J1 AC: app factory, error envelope, request-id middleware, /health,
/ready, /metrics). No network access beyond a fast-failing local socket.
"""

from __future__ import annotations

from api.main import create_app
from api.settings import ApiSettings
from fastapi.testclient import TestClient
from vms_common.config import DatabaseSettings


def _unreachable_settings() -> ApiSettings:
    # Port 1 on localhost: nothing listens there, so the connection is
    # refused immediately instead of timing out against a real network call.
    return ApiSettings(db=DatabaseSettings(dsn="postgresql+asyncpg://vms:vms@localhost:1/vms"))


def test_health_returns_ok() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_503_when_database_is_unreachable() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "down"


def test_metrics_exposes_prometheus_text_format() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_request_id_is_generated_when_absent() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        response = client.get("/health")
    assert response.headers["X-Request-ID"]


def test_request_id_is_echoed_when_supplied() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        response = client.get("/health", headers={"X-Request-ID": "test-request-id"})
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_404_returns_the_style_guide_error_envelope() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        response = client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "request_id" in body["error"]
