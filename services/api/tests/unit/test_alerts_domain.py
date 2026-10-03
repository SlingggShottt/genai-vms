"""Alert rules: threshold, titles, lifecycle, WebSocket role policy — no I/O (P3-J3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from api.domain.alerts import (
    EVENT_TYPE_LABELS,
    TRANSITIONS,
    WS_MESSAGE_ROLES,
    AlertTransitionError,
    check_transition,
    draft_from_event,
    is_fresh,
    label_for,
    role_may_receive,
    should_alert,
)
from vms_common.contracts.event import SEVERITY_ORDER, EventV1

FIXTURES = Path(__file__).resolve().parents[4] / "libs/vms_common/src/vms_common/fixtures"


def fixture_event(name: str) -> EventV1:
    return EventV1.model_validate(json.loads((FIXTURES / f"event_v1_{name}.json").read_text()))


# --- threshold -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "minimum", "expected"),
    [
        ("low", "medium", False),
        ("medium", "medium", True),  # inclusive
        ("high", "medium", True),
        ("critical", "medium", True),
        ("high", "high", True),
        ("medium", "high", False),
        ("critical", "critical", True),
        ("high", "critical", False),
        ("low", "low", True),
    ],
)
def test_events_alert_at_or_above_the_configured_severity(severity, minimum, expected) -> None:
    assert should_alert(severity, minimum) is expected


def test_the_threshold_covers_every_pair_consistently() -> None:
    for i, severity in enumerate(SEVERITY_ORDER):
        for j, minimum in enumerate(SEVERITY_ORDER):
            assert should_alert(severity, minimum) is (i >= j)


# --- titles --------------------------------------------------------------------------------------


def test_known_event_types_get_sentence_case_labels() -> None:
    assert label_for("intrusion") == "Intrusion"
    assert label_for("abandoned_object") == "Abandoned object"
    assert set(EVENT_TYPE_LABELS) == {
        "intrusion",
        "loitering",
        "crowding",
        "abandoned_object",
        "running",
    }


@pytest.mark.parametrize(
    ("event_type", "label"),
    [
        ("fire_detected", "Fire detected"),
        ("tailgating", "Tailgating"),
        ("door-forced", "Door forced"),
        ("_", "Event"),
    ],
)
def test_an_event_type_a_new_rule_adds_is_tidied_not_rejected(event_type, label) -> None:
    assert label_for(event_type) == label


def test_a_draft_carries_what_the_tray_needs() -> None:
    event = fixture_event("intrusion")
    draft = draft_from_event(event)
    assert draft.title == "Intrusion on cam02"
    assert (
        draft.event_id == event.event_id
        and draft.camera_id == "cam02"
        and draft.site_id == "rvce-campus"
    )
    assert draft.severity == "high" and draft.rule_id == "intrusion.after_hours"
    assert draft.caption == "A person in a dark jacket climbs over the gate into the fenced area."
    assert (draft.verification_status, draft.confidence) == ("verified", 0.84)
    assert (
        draft.keyframe_uris == event.keyframe_uris
        and draft.keyframe_uris is not event.keyframe_uris
    )
    assert (draft.start_ts, draft.end_ts) == (event.start_ts, event.end_ts)
    assert draft.zone_id == "01929e6c-0001-7000-8000-000000000001"


def test_a_skipped_verification_has_no_caption_or_confidence() -> None:
    draft = draft_from_event(fixture_event("running_skipped"))
    assert (draft.caption, draft.confidence, draft.verification_status) == (None, None, "skipped")
    assert draft.zone_id is None and draft.title == "Running on cam04"


# --- lifecycle -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "status", "allowed"),
    [
        ("acknowledge", "open", True),
        ("acknowledge", "acknowledged", False),
        ("acknowledge", "resolved", False),
        ("resolve", "open", True),  # a false alarm needs no acknowledgement first
        ("resolve", "acknowledged", True),
        ("resolve", "resolved", False),
    ],
)
def test_the_lifecycle_only_moves_forward(action, status, allowed) -> None:
    if allowed:
        check_transition(action, status)
    else:
        with pytest.raises(AlertTransitionError, match=f"cannot {action}.*already {status}"):
            check_transition(action, status)


def test_there_are_exactly_two_actions() -> None:
    assert set(TRANSITIONS) == {"acknowledge", "resolve"}


# --- websocket policy ----------------------------------------------------------------------------


@pytest.mark.parametrize("message_type", ["alert.created", "alert.updated", "job.progress"])
def test_alert_and_job_messages_are_for_operators_and_admins_only(message_type) -> None:
    assert role_may_receive("admin", message_type) and role_may_receive("operator", message_type)
    assert not role_may_receive("viewer", message_type)


@pytest.mark.parametrize("message_type", ["camera.status", "incident.ready"])
def test_status_and_incident_messages_are_for_everyone(message_type) -> None:
    assert all(role_may_receive(r, message_type) for r in ("admin", "operator", "viewer"))


def test_an_unknown_message_type_reaches_nobody() -> None:
    assert not any(role_may_receive(r, "something.new") for r in ("admin", "operator", "viewer"))


def test_an_unknown_role_receives_nothing() -> None:
    assert not any(role_may_receive("guest", t) for t in WS_MESSAGE_ROLES)


def test_the_policy_covers_the_designs_message_types() -> None:
    assert set(WS_MESSAGE_ROLES) == {
        "alert.created",
        "alert.updated",
        "camera.status",
        "job.progress",
        "incident.ready",
    }


# --- freshness (what is worth announcing) --------------------------------------------------------

END = datetime(2026, 10, 5, 10, 15, 42, tzinfo=UTC)


@pytest.mark.parametrize(
    ("age_s", "fresh"),
    [(0, True), (30, True), (900, True), (900.001, False), (86_400, False)],
)
def test_an_event_is_fresh_up_to_and_including_the_max_age(age_s: float, fresh: bool) -> None:
    now = END + timedelta(seconds=age_s)
    assert is_fresh(END, now=now, max_age_s=900) is fresh


def test_an_event_ending_in_the_future_counts_as_fresh() -> None:
    """Clock skew between the host that produced the event and this one."""
    assert is_fresh(END + timedelta(seconds=45), now=END, max_age_s=900)


def test_a_larger_window_keeps_an_older_event_fresh() -> None:
    now = END + timedelta(hours=2)
    assert not is_fresh(END, now=now, max_age_s=900)
    assert is_fresh(END, now=now, max_age_s=3 * 3600)
