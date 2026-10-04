"""Alert rules — no I/O (P3-J3, FR-ALR-01/02).

Which verified events become alerts, how an alert is titled, which lifecycle moves are legal,
and which WebSocket messages each role may receive. The database enforces the lifecycle too
(a CHECK on `core.alerts`); this is the layer that answers with a readable reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from vms_common.contracts.event import SEVERITY_ORDER, EventV1

EVENT_TYPE_LABELS: dict[str, str] = {
    "intrusion": "Intrusion",
    "loitering": "Loitering",
    "crowding": "Crowding",
    "abandoned_object": "Abandoned object",
    "running": "Running",
}


def label_for(event_type: str) -> str:
    """Sentence-case label for an event type; an unknown (new) type is tidied, not rejected."""
    if event_type in EVENT_TYPE_LABELS:
        return EVENT_TYPE_LABELS[event_type]
    return event_type.replace("_", " ").replace("-", " ").strip().capitalize() or "Event"


def should_alert(severity: str, min_severity: str) -> bool:
    """True when `severity` is at or above `min_severity`."""
    return SEVERITY_ORDER.index(severity) >= SEVERITY_ORDER.index(min_severity)  # type: ignore[arg-type]


def is_fresh(end_ts: datetime, *, now: datetime, max_age_s: float) -> bool:
    """Did the event end recently enough to be worth announcing? An end time in the future
    (clock skew between hosts) counts as fresh."""
    return (now - end_ts).total_seconds() <= max_age_s


@dataclass(frozen=True)
class AlertDraft:
    """Everything a new alert row needs, derived from one `event.v1`."""

    event_id: str
    site_id: str
    camera_id: str
    event_type: str
    severity: str
    rule_id: str
    zone_id: str | None
    title: str
    caption: str | None
    verification_status: str
    confidence: float | None
    start_ts: datetime
    end_ts: datetime
    keyframe_uris: list[str]


def draft_from_event(event: EventV1) -> AlertDraft:
    return AlertDraft(
        event_id=event.event_id,
        site_id=event.site_id,
        camera_id=event.camera_id,
        event_type=event.event_type,
        severity=event.severity,
        rule_id=event.rule_id,
        zone_id=event.zone_id,
        title=f"{label_for(event.event_type)} on {event.camera_id}",
        caption=event.verification.caption,
        verification_status=event.verification.status,
        confidence=event.verification.confidence,
        start_ts=event.start_ts,
        end_ts=event.end_ts,
        keyframe_uris=list(event.keyframe_uris),
    )


# --- lifecycle ---------------------------------------------------------------------------------

# design_architecture.md §7.6: verified -> acknowledged -> resolved. An operator may also resolve
# an alert that was never acknowledged (a false alarm needs no ceremony).
TRANSITIONS: dict[str, frozenset[str]] = {
    "acknowledge": frozenset({"open"}),
    "resolve": frozenset({"open", "acknowledged"}),
}


class AlertTransitionError(ValueError):
    """The alert is not in a state the action applies to."""


def check_transition(action: str, current_status: str) -> None:
    if current_status not in TRANSITIONS[action]:
        raise AlertTransitionError(f"cannot {action} an alert that is already {current_status}")


# --- WebSocket message policy ------------------------------------------------------------------

# design_architecture.md §9: alerts are operator-and-above (a viewer sees no alert traffic at all);
# camera status and finished incidents are for everyone; job progress is operational.
WS_MESSAGE_ROLES: dict[str, frozenset[str]] = {
    "alert.created": frozenset({"admin", "operator"}),
    "alert.updated": frozenset({"admin", "operator"}),
    "camera.status": frozenset({"admin", "operator", "viewer"}),
    "job.progress": frozenset({"admin", "operator"}),
    "incident.ready": frozenset({"admin", "operator", "viewer"}),
}


def role_may_receive(role: str, message_type: str) -> bool:
    """False for an unknown message type: new types must be added to the policy explicitly
    rather than leak to every role by default."""
    return role in WS_MESSAGE_ROLES.get(message_type, frozenset())
