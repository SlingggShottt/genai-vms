"""Prometheus metric helpers (style_guide.md §A.1 naming: `vms_<area>_<name>_<unit>`).

Thin factories over prometheus_client so every service gets the naming
convention for free instead of hand-formatting strings, e.g.:

    segments_total = counter("ingest", "segments", "total",
                              "Segments announced", labelnames=("camera",))
    # -> vms_ingest_segments_total{camera="cam03"}

matches the metric names catalogued in design_architecture.md §15.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


def _metric_name(area: str, name: str, unit: str) -> str:
    return f"vms_{area}_{name}_{unit}"


def counter(
    area: str, name: str, unit: str, description: str, labelnames: tuple[str, ...] = ()
) -> Counter:
    return Counter(_metric_name(area, name, unit), description, labelnames)


def gauge(
    area: str, name: str, unit: str, description: str, labelnames: tuple[str, ...] = ()
) -> Gauge:
    return Gauge(_metric_name(area, name, unit), description, labelnames)


def histogram(
    area: str,
    name: str,
    unit: str,
    description: str,
    labelnames: tuple[str, ...] = (),
    buckets: tuple[float, ...] | None = None,
) -> Histogram:
    kwargs = {"buckets": buckets} if buckets is not None else {}
    return Histogram(_metric_name(area, name, unit), description, labelnames, **kwargs)


_served: set[int] = set()


def serve(port: int) -> None:
    """Expose this process's metrics at `http://0.0.0.0:<port>/metrics` for Prometheus (the
    workers have no HTTP server of their own; the api and retrieval mount `/metrics` instead).
    Safe to call twice and never fatal: a port already in use costs the metrics, not the service."""
    if port in _served:
        return
    from prometheus_client import start_http_server

    from vms_common.logging import get_logger

    try:
        start_http_server(port)
    except OSError as exc:
        get_logger(__name__).warning("metrics_port_unavailable", port=port, error=str(exc))
        return
    _served.add(port)
