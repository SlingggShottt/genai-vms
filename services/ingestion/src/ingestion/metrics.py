"""Prometheus metrics for ingestion (design_architecture.md §15)."""

from vms_common.metrics import counter

segments_total = counter(
    "ingest", "segments", "total", "Segments announced on vms.segments.v1", labelnames=("camera",)
)
stream_reconnects_total = counter(
    "stream", "reconnects", "total", "RTSP reconnect attempts", labelnames=("camera",)
)
