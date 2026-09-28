"""Declarative base shared by every ORM model, with a fixed naming
convention so Alembic autogenerate produces stable constraint/index names
across the single Alembic history (style_guide.md §A.4, design_architecture.md §6.1).
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every table across every schema (core, media, vision,
    events, reasoning, retrieval) — one Alembic history, one metadata object.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
