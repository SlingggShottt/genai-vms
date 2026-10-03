"""Unit tests for the `core.alerts` model — metadata shape only, no DB (P3-J3)."""

from __future__ import annotations

from vms_db.base import Base
from vms_db.models.core import SCHEMA, AlertStatus


def test_alerts_is_registered_in_the_core_schema() -> None:
    assert Base.metadata.tables["core.alerts"].schema == SCHEMA


def test_a_raised_event_has_at_most_one_alert() -> None:
    alerts = Base.metadata.tables["core.alerts"]
    assert alerts.c.event_id.unique is True  # the idempotency key for a redelivered event.v1


def test_people_who_handled_an_alert_are_kept_as_history_when_they_leave() -> None:
    alerts = Base.metadata.tables["core.alerts"]
    for column in (alerts.c.acknowledged_by, alerts.c.resolved_by):
        (fk,) = column.foreign_keys
        assert fk.target_fullname == "core.users.id" and fk.ondelete == "SET NULL"


def test_the_group_is_a_soft_reference() -> None:
    # the group lives in the events schema and is merged or aged out on its own schedule
    assert not Base.metadata.tables["core.alerts"].c.group_id.foreign_keys


def test_the_table_carries_its_own_lifecycle_rules() -> None:
    names = {c.name for c in Base.metadata.tables["core.alerts"].constraints if c.name}
    assert {"ck_alerts_status", "ck_alerts_severity", "ck_alerts_lifecycle"} <= names


def test_alert_status_values() -> None:
    assert [s.value for s in AlertStatus] == ["open", "acknowledged", "resolved"]
