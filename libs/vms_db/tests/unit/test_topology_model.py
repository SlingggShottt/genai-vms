"""Unit tests for the `core.topology_edges` model — metadata shape only, no DB (P3-J1)."""

from __future__ import annotations

from vms_db.base import Base
from vms_db.models.core import SCHEMA, EdgeType


def test_topology_edges_is_registered_in_the_core_schema() -> None:
    table = Base.metadata.tables["core.topology_edges"]
    assert table.schema == SCHEMA


def test_both_camera_columns_are_foreign_keys_to_cameras() -> None:
    table = Base.metadata.tables["core.topology_edges"]
    for column in (table.c.from_camera_id, table.c.to_camera_id):
        assert {fk.target_fullname for fk in column.foreign_keys} == {"core.cameras.id"}
        assert all(fk.ondelete == "CASCADE" for fk in column.foreign_keys)


def test_edge_type_has_two_values() -> None:
    assert {t.value for t in EdgeType} == {"overlap", "transit"}


def test_the_table_carries_its_own_integrity_rules() -> None:
    table = Base.metadata.tables["core.topology_edges"]
    names = {c.name for c in table.constraints if c.name}
    assert {
        "ck_topology_edges_distinct_cameras",
        "ck_topology_edges_edge_parameters",
        "uq_topology_edges_pair",
    } <= names
    assert "uq_topology_edges_overlap_pair" in {i.name for i in table.indexes}
