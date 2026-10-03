"""Prometheus metrics for the api's real-time and alerting paths (design_architecture.md §15)."""

from vms_common.metrics import counter, gauge

alerts_created_total = counter(
    "api", "alerts_created", "total", "Alerts raised from verified events", labelnames=("severity",)
)
alerts_skipped_total = counter(
    "api",
    "alerts_skipped",
    "total",
    "Verified events that raised no alert, by reason (below_threshold|duplicate)",
    labelnames=("reason",),
)
alert_actions_total = counter(
    "api", "alert_actions", "total", "Operator actions on alerts", labelnames=("action",)
)
ws_connections = gauge(
    "api", "ws_connections", "count", "WebSocket clients connected to this replica"
)
ws_messages_total = counter(
    "api", "ws_messages", "total", "Messages queued for WebSocket clients", labelnames=("type",)
)
ws_dropped_total = counter(
    "api", "ws_dropped", "total", "Clients disconnected for falling too far behind"
)
notifications_total = counter(
    "api",
    "notifications",
    "total",
    "Notification attempts by channel and outcome (ok|error|timeout)",
    labelnames=("channel", "result"),
)
ws_publish_errors_total = counter(
    "api", "ws_publish_errors", "total", "WebSocket pushes that could not reach Redis"
)
alert_announcements_skipped_total = counter(
    "api",
    "alert_announcements_skipped",
    "total",
    "Alerts stored but not announced, by reason (stale)",
    labelnames=("reason",),
)
