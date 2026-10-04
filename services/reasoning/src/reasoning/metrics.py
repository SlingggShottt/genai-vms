"""Prometheus metrics for reasoning (design §15)."""

from vms_common.metrics import counter, gauge, histogram

job_seconds = histogram(
    "reasoning",
    "job",
    "seconds",
    "Seconds a reasoning job spent in each stage",
    labelnames=("stage",),
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200),
)
jobs_total = counter(
    "reasoning", "jobs", "total", "Reasoning jobs finished", labelnames=("outcome",)
)
queue_depth = gauge("reasoning", "queue_depth", "jobs", "Reasoning jobs waiting for the worker")
daily_reports_total = counter(
    "reasoning", "daily_reports", "total", "Daily reports written", labelnames=("narrative",)
)
