"""Unit tests for the correlation tables — metadata shape only, no DB (P3-J2)."""

from __future__ import annotations

from vms_db.base import Base
from vms_db.models.correlation import SCHEMA


def test_both_tables_live_in_the_events_schema() -> None:
    for name in ("events.correlation_groups", "events.correlation_links"):
        assert Base.metadata.tables[name].schema == SCHEMA == "events"


def test_links_belong_to_a_group_and_go_with_it() -> None:
    links = Base.metadata.tables["events.correlation_links"]
    (fk,) = links.c.group_id.foreign_keys
    assert fk.target_fullname == "events.correlation_groups.id" and fk.ondelete == "CASCADE"


def test_a_merged_group_points_at_its_survivor() -> None:
    groups = Base.metadata.tables["events.correlation_groups"]
    (fk,) = groups.c.merged_into.foreign_keys
    assert fk.target_fullname == "events.correlation_groups.id"
    assert fk.ondelete == "CASCADE"  # SET NULL would break the merged-needs-a-survivor CHECK


def test_the_groups_table_carries_its_own_integrity_rules() -> None:
    groups = Base.metadata.tables["events.correlation_groups"]
    names = {c.name for c in groups.constraints if c.name}
    assert {
        "ck_correlation_groups_status",
        "ck_correlation_groups_max_severity",
        "ck_correlation_groups_revision",
        "ck_correlation_groups_window",
        "ck_correlation_groups_merged_into",
        "ck_correlation_groups_has_events",
    } <= names


def test_the_lookups_the_service_makes_are_indexed() -> None:
    groups = Base.metadata.tables["events.correlation_groups"]
    indexes = {i.name: i for i in groups.indexes}
    assert (
        indexes["ix_events_correlation_groups_event_ids"].dialect_options["postgresql"]["using"]
        == "gin"
    )
    assert "ix_events_correlation_groups_open" in indexes
    assert "ix_events_correlation_groups_publish_pending" in indexes


def test_a_pair_of_events_is_linked_at_most_once() -> None:
    links = Base.metadata.tables["events.correlation_links"]
    assert "uq_correlation_links_pair" in {c.name for c in links.constraints if c.name}
