"""Camera-graph source: `GET /internal/v1/topology` with a `config/topology.yaml` fallback
(design_architecture.md §16), refreshed periodically by the caller.

Same shape as the events service's `zones_source` — duplicated rather than shared because
services never import each other (CLAUDE.md); lift both into `vms_common` if a third consumer
appears. A refresh that fails keeps the last graph; only the *first* load can fail the service.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml
from vms_common.contracts.topology import TopologyEdgeInternal, TopologyInternalResponse
from vms_common.logging import get_logger

log = get_logger(__name__)


async def fetch_topology_from_api(
    base_url: str,
    *,
    service_token: str = "",
    timeout_s: float = 5.0,
    client: httpx.AsyncClient | None = None,
) -> list[TopologyEdgeInternal]:
    """`GET /internal/v1/topology`. Raises on any failure — the caller decides the fallback."""
    headers = {"Authorization": f"Bearer {service_token}"} if service_token else {}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.get(f"{base_url.rstrip('/')}/internal/v1/topology", headers=headers)
        response.raise_for_status()
        return TopologyInternalResponse.model_validate(response.json()).edges
    finally:
        if owns_client:
            await client.aclose()


def load_topology_from_yaml(path: str | Path) -> list[TopologyEdgeInternal]:
    """Load the `config/topology.yaml` fallback (same shape as the API response). A missing
    file is an empty graph — every event then becomes its own group — not an error: a site
    that has not drawn its camera links yet still gets events and alerts."""
    file = Path(path)
    if not file.exists():
        log.warning("topology_yaml_missing_using_empty_graph", path=str(file))
        return []
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    return TopologyInternalResponse.model_validate(raw).edges


async def resolve_topology(
    *,
    api_base_url: str | None,
    service_token: str,
    yaml_fallback_path: str | Path,
    client: httpx.AsyncClient | None = None,
) -> list[TopologyEdgeInternal]:
    """Try the internal API first; fall back to YAML on any HTTP error."""
    if api_base_url:
        try:
            return await fetch_topology_from_api(
                api_base_url, service_token=service_token, client=client
            )
        except httpx.HTTPError as exc:
            log.warning("topology_api_unavailable_using_yaml_fallback", error=str(exc))
    return load_topology_from_yaml(yaml_fallback_path)
