"""Prometheus metrics for events (design_architecture.md §15)."""

from vms_common.metrics import counter

candidates_total = counter(
    "events",
    "candidates",
    "total",
    "Rule-engine candidates created (not counting extensions or replays)",
    labelnames=("rule",),
)
