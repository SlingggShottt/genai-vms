"""Prometheus metrics for the indexer (design §15)."""

from vms_common.metrics import counter, histogram

segments_total = counter("indexer", "segments", "total", "Twins indexed", labelnames=("camera",))
# Segment end → searchable: the pipeline's end-to-end lag.
index_lag_seconds = histogram(
    "indexer",
    "lag",
    "seconds",
    "Seconds from a segment's end to its twin being indexed",
    buckets=(2, 5, 10, 20, 30, 60, 120, 300, 900, 3600),
)
knowledge_docs_total = counter(
    "indexer",
    "knowledge_docs",
    "total",
    "Texts written to the knowledge collection",
    labelnames=("doc_type",),
)
