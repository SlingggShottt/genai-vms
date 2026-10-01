"""Unit tests for the `events.candidates` model — metadata shape only, no DB (P3-D1)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint
from vms_db.base import Base
from vms_db.models import Candidate
from vms_db.models.events import CANDIDATE_SEVERITIES, CANDIDATE_STATUSES, SCHEMA


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
