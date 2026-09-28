"""Camera list source: `GET /internal/v1/cameras` with a `config/cameras.yaml`
fallback (design_architecture.md §16; DIVYANSH.md: "use config/cameras.yaml
fallback until P1-J3 merges"), refreshed periodically by the caller (FR-CAM-05).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml
from vms_common.contracts.camera import CameraInternal, CamerasInternalResponse
from vms_common.logging import get_logger

log = get_logger(__name__)


async def fetch_cameras_from_api(
    base_url: str,
    *,
    service_token: str = "",
    timeout_s: float = 5.0,
    client: httpx.AsyncClient | None = None,
) -> list[CameraInternal]:
    """`GET /internal/v1/cameras`. Raises on any failure — caller decides fallback.

    Pass `client` (e.g. built with a mock transport) in tests instead of
    letting this open a real connection.
    """
    headers = {"Authorization": f"Bearer {service_token}"} if service_token else {}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.get(f"{base_url.rstrip('/')}/internal/v1/cameras", headers=headers)
        response.raise_for_status()
        return CamerasInternalResponse.model_validate(response.json()).cameras
    finally:
        if owns_client:
            await client.aclose()


def load_cameras_from_yaml(path: str | Path) -> list[CameraInternal]:
    """Load the `config/cameras.yaml` fallback (same shape as the API response)."""
    raw = yaml.safe_load(Path(path).read_text())
    return CamerasInternalResponse.model_validate(raw).cameras


async def resolve_cameras(
    *,
    api_base_url: str | None,
    service_token: str,
    yaml_fallback_path: str | Path,
    client: httpx.AsyncClient | None = None,
) -> list[CameraInternal]:
    """Try the internal API first; fall back to YAML on any error."""
    if api_base_url:
        try:
            return await fetch_cameras_from_api(
                api_base_url, service_token=service_token, client=client
            )
        except httpx.HTTPError as exc:
            log.warning("camera_api_unavailable_using_yaml_fallback", error=str(exc))
    return load_cameras_from_yaml(yaml_fallback_path)
