"""Zone list source: `GET /internal/v1/zones` with a `config/zones.yaml`
fallback (design_architecture.md §16), refreshed periodically by the
caller (FR-CAM-05). Same pattern as `ingestion.adapters.camera_source`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml
from vms_common.contracts.zones import ZoneInternal, ZonesInternalResponse
from vms_common.logging import get_logger

log = get_logger(__name__)


async def fetch_zones_from_api(
    base_url: str,
    *,
    service_token: str = "",
    timeout_s: float = 5.0,
    client: httpx.AsyncClient | None = None,
) -> list[ZoneInternal]:
    """`GET /internal/v1/zones`. Raises on any failure — caller decides fallback."""
    headers = {"Authorization": f"Bearer {service_token}"} if service_token else {}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.get(f"{base_url.rstrip('/')}/internal/v1/zones", headers=headers)
        response.raise_for_status()
        return ZonesInternalResponse.model_validate(response.json()).zones
    finally:
        if owns_client:
            await client.aclose()


def load_zones_from_yaml(path: str | Path) -> list[ZoneInternal]:
    """Load the `config/zones.yaml` fallback (same shape as the API response)."""
    raw = yaml.safe_load(Path(path).read_text())
    return ZonesInternalResponse.model_validate(raw).zones


async def resolve_zones(
    *,
    api_base_url: str | None,
    service_token: str,
    yaml_fallback_path: str | Path,
    client: httpx.AsyncClient | None = None,
) -> list[ZoneInternal]:
    """Try the internal API first; fall back to YAML on any error."""
    if api_base_url:
        try:
            return await fetch_zones_from_api(
                api_base_url, service_token=service_token, client=client
            )
        except httpx.HTTPError as exc:
            log.warning("zones_api_unavailable_using_yaml_fallback", error=str(exc))
    return load_zones_from_yaml(yaml_fallback_path)
