"""Gateway metrics (design_architecture.md §15; names follow style_guide.md §A.1).

`vms_llm_request_seconds` and `vms_llm_tokens_total` are the two the backlog names. The
design lists them with labels {provider, task}; `status` and `kind` are added so one
panel can show error rate and prompt-vs-completion tokens, and `sum by (provider, task)`
still gives the designed series.
"""

from __future__ import annotations

from vms_common.metrics import counter, histogram

# A 3B model on a 4 GB GPU answers in seconds, a cold start in tens of seconds, a hosted
# model in under a few — the buckets cover 100 ms .. 3 min.
_LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120, 180)

request_seconds = histogram(
    "llm",
    "request",
    "seconds",
    "One model call (not a whole gateway call: validation retries and fallbacks each count)",
    labelnames=("provider", "task", "status"),
    buckets=_LATENCY_BUCKETS,
)
tokens_total = counter(
    "llm",
    "tokens",
    "total",
    "Tokens the provider reported, by direction",
    labelnames=("provider", "task", "kind"),
)
retries_total = counter(
    "llm",
    "retries",
    "total",
    "Calls repeated because the reply did not validate against response_model",
    labelnames=("task",),
)
fallbacks_total = counter(
    "llm",
    "fallbacks",
    "total",
    "Times a task moved on to its next model after a failure",
    labelnames=("task",),
)
cache_total = counter(
    "llm",
    "cache",
    "total",
    "Response-cache lookups by outcome (hit|miss)",
    labelnames=("task", "result"),
)
lease_wait_seconds = histogram(
    "llm",
    "lease_wait",
    "seconds",
    "Time a call queued for the GPU lease",
    labelnames=("outcome",),
    buckets=(0.01, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
