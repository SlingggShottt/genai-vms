"""Prometheus metrics for retrieval (design §15)."""

from vms_common.metrics import counter, histogram

search_stage_seconds = histogram(
    "search",
    "stage",
    "seconds",
    "Seconds spent in each stage of a search",
    labelnames=("stage",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 15, 30, 60, 120),
)
searches_total = counter(
    "search", "requests", "total", "Searches served", labelnames=("kind", "mode")
)
assistant_turns_total = counter(
    "assistant", "turns", "total", "Assistant turns", labelnames=("outcome",)
)
