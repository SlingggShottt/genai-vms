"""Prometheus metrics for correlation (design_architecture.md §15)."""

from vms_common.metrics import counter, gauge

events_total = counter(
    "correlation",
    "events",
    "total",
    "event.v1 messages handled, by what became of them (new_group|joined|merged|duplicate)",
    labelnames=("result",),
)
links_total = counter(
    "correlation",
    "links",
    "total",
    "Links recorded between events",
    labelnames=("edge_type",),
)
groups_closed_total = counter(
    "correlation", "groups_closed", "total", "Groups closed because nothing could still link"
)
published_total = counter(
    "correlation",
    "published",
    "total",
    "correlation.v1 messages sent, by group status",
    labelnames=("status",),
)
open_groups = gauge("correlation", "open_groups", "count", "Groups currently open")
sweep_errors_total = counter(
    "correlation", "sweep_errors", "total", "Sweeps that failed (retried on the next tick)"
)
