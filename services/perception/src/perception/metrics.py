"""Prometheus metrics for perception (design §15)."""

from vms_common.metrics import counter, histogram

segments_total = counter(
    "perception", "segments", "total", "Segments turned into twins", labelnames=("camera",)
)
latency_seconds = histogram(
    "perception",
    "latency",
    "seconds",
    "Seconds from a segment's end to its twin being published",
    buckets=(2, 5, 10, 20, 30, 60, 120, 300, 900),
)
