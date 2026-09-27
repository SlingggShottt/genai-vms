"""Tests for perception.adapters.zones_source — YAML fallback (real file
I/O) and the HTTP path (mocked transport, no real network).
"""

from pathlib import Path

import httpx
import pytest
from perception.adapters.zones_source import (
    fetch_zones_from_api,
    load_zones_from_yaml,
    resolve_zones,
)

ZONES_YAML = """
zones:
  - id: zone01
    camera_id: cam01
    name: entrance
    zone_type: entrance
    polygon:
      - [0.3, 0.2]
      - [0.7, 0.2]
      - [0.7, 0.6]
      - [0.3, 0.6]
"""


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_load_zones_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "zones.yaml"
    path.write_text(ZONES_YAML)

    zones = load_zones_from_yaml(path)

    assert len(zones) == 1
    assert zones[0].camera_id == "cam01"
    assert zones[0].zone_type == "entrance"


@pytest.mark.asyncio
async def test_fetch_zones_from_api_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/internal/v1/zones"
        return httpx.Response(
            200,
            json={
                "zones": [
                    {
                        "id": "z1",
                        "camera_id": "cam01",
                        "name": "entrance",
                        "zone_type": "entrance",
                        "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]],
                    }
                ]
            },
        )

    async with _mock_client(handler) as client:
        zones = await fetch_zones_from_api("http://api:8000/api/v1", client=client)

    assert len(zones) == 1
    assert zones[0].name == "entrance"


@pytest.mark.asyncio
async def test_resolve_zones_falls_back_to_yaml_when_api_unset(tmp_path: Path) -> None:
    path = tmp_path / "zones.yaml"
    path.write_text(ZONES_YAML)

    zones = await resolve_zones(api_base_url=None, service_token="", yaml_fallback_path=path)

    assert len(zones) == 1


@pytest.mark.asyncio
async def test_resolve_zones_falls_back_to_yaml_when_api_errors(tmp_path: Path) -> None:
    path = tmp_path / "zones.yaml"
    path.write_text(ZONES_YAML)

    async with _mock_client(lambda request: httpx.Response(503)) as client:
        zones = await resolve_zones(
            api_base_url="http://api:8000/api/v1",
            service_token="",
            yaml_fallback_path=path,
            client=client,
        )

    assert len(zones) == 1
