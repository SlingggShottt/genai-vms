"""Tests for ingestion.adapters.camera_source — YAML fallback (real file I/O)
and the HTTP path (mocked transport, no real network — style_guide.md §A.1:
"Tests never hit the network or real LLMs").
"""

from pathlib import Path

import httpx
import pytest
from ingestion.adapters.camera_source import (
    fetch_cameras_from_api,
    load_cameras_from_yaml,
    resolve_cameras,
)

CAMERAS_YAML = """
cameras:
  - id: cam01
    code: cam01
    name: North Gate
    rtsp_url: rtsp://mediamtx:8554/cam01
    site_id: rvce-campus
    enabled: true
  - id: cam02
    code: cam02
    name: Disabled Camera
    rtsp_url: rtsp://mediamtx:8554/cam02
    site_id: rvce-campus
    enabled: false
"""


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_load_cameras_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "cameras.yaml"
    path.write_text(CAMERAS_YAML)

    cameras = load_cameras_from_yaml(path)

    assert [c.code for c in cameras] == ["cam01", "cam02"]
    assert cameras[0].enabled is True
    assert cameras[1].enabled is False


@pytest.mark.asyncio
async def test_fetch_cameras_from_api_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/internal/v1/cameras"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "cameras": [
                    {
                        "id": "1",
                        "code": "cam01",
                        "name": "North Gate",
                        "rtsp_url": "rtsp://mediamtx:8554/cam01",
                        "site_id": "rvce-campus",
                    }
                ]
            },
        )

    async with _mock_client(handler) as client:
        cameras = await fetch_cameras_from_api(
            "http://api:8000/api/v1", service_token="test-token", client=client
        )

    assert len(cameras) == 1
    assert cameras[0].code == "cam01"


@pytest.mark.asyncio
async def test_fetch_cameras_from_api_raises_on_http_error() -> None:
    async with _mock_client(lambda request: httpx.Response(500)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_cameras_from_api("http://api:8000/api/v1", client=client)


@pytest.mark.asyncio
async def test_resolve_cameras_falls_back_to_yaml_when_api_unset(tmp_path: Path) -> None:
    path = tmp_path / "cameras.yaml"
    path.write_text(CAMERAS_YAML)

    cameras = await resolve_cameras(api_base_url=None, service_token="", yaml_fallback_path=path)

    assert [c.code for c in cameras] == ["cam01", "cam02"]


@pytest.mark.asyncio
async def test_resolve_cameras_falls_back_to_yaml_when_api_errors(tmp_path: Path) -> None:
    path = tmp_path / "cameras.yaml"
    path.write_text(CAMERAS_YAML)

    async with _mock_client(lambda request: httpx.Response(503)) as client:
        cameras = await resolve_cameras(
            api_base_url="http://api:8000/api/v1",
            service_token="",
            yaml_fallback_path=path,
            client=client,
        )

    assert [c.code for c in cameras] == ["cam01", "cam02"]
