"""Unit tests for the `core` schema models — metadata shape only, no DB
(P1-J1). Catches accidental table/schema renames before they reach a
migration.
"""

from __future__ import annotations

from vms_db.base import Base
from vms_db.models.core import SCHEMA, UserRole


def test_core_tables_are_registered_on_base_metadata() -> None:
    table_names = {table.name for table in Base.metadata.tables.values()}
    assert {"users", "refresh_tokens", "cameras", "audit_log"} <= table_names


def test_core_tables_live_in_the_core_schema() -> None:
    for full_name, table in Base.metadata.tables.items():
        if table.name in {"users", "refresh_tokens", "cameras", "audit_log"}:
            assert table.schema == SCHEMA, full_name


def test_users_email_is_unique() -> None:
    users = Base.metadata.tables["core.users"]
    assert users.c.email.unique is True


def test_user_role_has_three_values() -> None:
    assert {r.value for r in UserRole} == {"admin", "operator", "viewer"}
