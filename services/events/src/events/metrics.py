"""Prometheus metrics for events (design_architecture.md §15)."""

from vms_common.metrics import counter, histogram

candidates_total = counter(
    "events",
    "candidates",
    "total",
    "Rule-engine candidates created (not counting extensions or replays)",
    labelnames=("rule",),
)

# `vms_events_verified_ratio{rule}` (design §15) is verified / (verified + rejected) of this.
verifications_total = counter(
    "events",
    "verifications",
    "total",
    "VLM gate outcomes per candidate: verified, skipped, rejected, or held for a later try",
    labelnames=("rule", "outcome"),
)
verification_errors_total = counter(
    "events",
    "verification_errors",
    "total",
    "Candidates the gate failed on unexpectedly (they are retried with back-off)",
    labelnames=("rule",),
)
verification_seconds = histogram(
    "events",
    "verification",
    "seconds",
    "Time the VLM took to judge one candidate",
    buckets=(0.5, 1, 2, 4, 8, 15, 30, 60, 120),
)
published_total = counter(
    "events",
    "published",
    "total",
    "event.v1 messages sent",
    labelnames=("status",),
)
