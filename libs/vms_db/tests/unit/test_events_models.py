"""Unit tests for the `events.candidates` and `events.events` models — metadata shape only, no DB
(P3-D1, P3-D4)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint
from vms_db.base import Base
from vms_db.models import Candidate, Event
from vms_db.models.events import (
    CANDIDATE_SEVERITIES,
    CANDIDATE_STATUSES,
    EVENT_STATUSES,
    SCHEMA,
)


def _table():
    return Base.metadata.tables["events.candidates"]


def test_candidates_is_registered_in_the_events_schema() -> None:
    assert _table().schema == SCHEMA == "events"
    assert Candidate.__table__ is _table()


def test_candidates_columns_cover_what_the_rule_engine_persists() -> None:
    assert set(_table().c.keys()) == {
        "id",
        "site_id",
        "camera_id",
        "rule_id",
        "event_type",
        "severity",
        "zone_id",
        "zone_name",
        "track_ids",
        "segment_ids",
        "start_ts",
        "end_ts",
        "rule_score",
        "status",
        "details",
        "created_at",
        "updated_at",
        "verify_attempts",
        "verify_first_at",
        "verify_not_before",
    }


def test_candidates_primary_key_is_the_caller_supplied_id() -> None:
    # The events service derives it deterministically so replays upsert.
    assert [c.name for c in _table().primary_key.columns] == ["id"]
    assert _table().c.id.server_default is None


def test_status_and_severity_are_constrained_with_conventional_names() -> None:
    checks = {
        c.name: str(c.sqltext) for c in _table().constraints if isinstance(c, CheckConstraint)
    }

    assert set(checks) == {"ck_candidates_status", "ck_candidates_severity"}
    for value in CANDIDATE_STATUSES:
        assert repr(value) in checks["ck_candidates_status"]
    for value in CANDIDATE_SEVERITIES:
        assert repr(value) in checks["ck_candidates_severity"]


def test_candidates_are_indexed_for_camera_timeline_and_status_queries() -> None:
    assert {i.name for i in _table().indexes} == {
        "ix_events_candidates_camera_id_start_ts",
        "ix_events_candidates_status",
    }


def test_a_candidate_waits_for_the_gate_with_no_tries_yet_by_default() -> None:
    assert _table().c.verify_attempts.nullable is False
    assert str(_table().c.verify_attempts.server_default.arg) == "0"
    assert _table().c.verify_first_at.nullable is True
    assert _table().c.verify_not_before.nullable is True


def _events():
    return Base.metadata.tables["events.events"]


def test_events_is_registered_in_the_events_schema() -> None:
    assert _events().schema == SCHEMA == "events"
    assert Event.__table__ is _events()


def test_events_columns_cover_what_the_gate_decides_and_event_v1_needs() -> None:
    assert set(_events().c.keys()) == {
        "id",
        "site_id",
        "camera_id",
        "event_type",
        "severity",
        "rule_id",
        "rule_score",
        "zone_id",
        "zone_name",
        "track_ids",
        "segment_ids",
        "keyframe_uris",
        "start_ts",
        "end_ts",
        "status",
        "verification",
        "published_at",
        "created_at",
    }


def test_an_event_is_the_candidate_it_was_made_from_so_the_id_is_supplied() -> None:
    assert [c.name for c in _events().primary_key.columns] == ["id"]
    assert _events().c.id.server_default is None


def test_events_are_constrained_with_conventional_names() -> None:
    checks = {
        c.name: str(c.sqltext) for c in _events().constraints if isinstance(c, CheckConstraint)
    }

    assert set(checks) == {
        "ck_events_status",
        "ck_events_severity",
        "ck_events_window",
        "ck_events_rule_score",
        "ck_events_rejected_unpublished",
        "ck_events_verification_object",
    }
    for value in EVENT_STATUSES:
        assert repr(value) in checks["ck_events_status"]
    assert EVENT_STATUSES == ("verified", "skipped", "rejected")


def test_events_are_indexed_for_the_timeline_and_for_what_is_waiting_to_be_published() -> None:
    indexes = {i.name: i for i in _events().indexes}

    assert set(indexes) == {
        "ix_events_events_camera_id_start_ts",
        "ix_events_events_publish_pending",
    }
    pending = indexes["ix_events_events_publish_pending"]
    where = str(pending.dialect_options["postgresql"]["where"])
    assert "published_at IS NULL" in where and "'verified'" in where and "'skipped'" in where
    assert "'rejected'" not in where
