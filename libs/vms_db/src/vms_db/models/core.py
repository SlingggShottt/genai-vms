"""ORM models for the `core` schema — accounts, roles, cameras, zones, audit
(design_architecture.md §6.1). Owner: J. `core.alerts`, `core.cases`
land with the stories that need them (P3-J3, P6-J4).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from vms_common.ids import uuid7
from vms_common.types import CameraCode

from vms_db.base import Base

SCHEMA = "core"


class UserRole(enum.StrEnum):
    """SRS §2.2 user classes."""

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            schema=SCHEMA,
            native_enum=True,
            # Store the lowercase enum *values* ("admin") that migration 0001's
            # PG type declares, not the member names ("ADMIN") SQLAlchemy sends
            # by default.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """Rotating refresh tokens (FR-AUTH-01) — stored hashed, never the raw token."""

    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Camera(Base):
    """`core.cameras` — field names match the `CameraInternal` contract in
    `vms_common.contracts.camera`.
    """

    __tablename__ = "cameras"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    code: Mapped[CameraCode] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    rtsp_url: Mapped[str] = mapped_column(Text, nullable=False)
    site_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    location_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lat: Mapped[float | None] = mapped_column(nullable=True)
    lon: Mapped[float | None] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ZoneType(enum.StrEnum):
    """FR-CAM-03. `restricted`/`entrance`/`exit` are the types event rules
    (P3-D1) key off of; `generic` is anything else worth naming/drawing.
    """

    GENERIC = "generic"
    RESTRICTED = "restricted"
    ENTRANCE = "entrance"
    EXIT = "exit"


class Zone(Base):
    """`core.zones` — field names match `ZoneInternal`
    (`vms_common.contracts.zones`), the shape `GET /internal/v1/zones`
    returns to perception/events. `polygon`/`schedule` are stored as JSONB
    rather than normalized tables — a polygon is always read/written whole,
    never queried by individual point (same reasoning as `core.zones`'
    design_architecture.md §6.1 column, and as `attributes_summary`
    elsewhere in this schema).
    """

    __tablename__ = "zones"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    zone_type: Mapped[ZoneType] = mapped_column(
        Enum(
            ZoneType,
            name="zone_type",
            schema=SCHEMA,
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    polygon: Mapped[list] = mapped_column(JSONB, nullable=False)
    schedule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EdgeType(enum.StrEnum):
    """FR-CAM-04 / design_architecture.md §7.5. `overlap`: the two cameras see the
    same area, so their events link when the time windows intersect (after
    widening each by `tolerance_s`). `transit`: B is reachable from A in
    `min_s..max_s` seconds, so an event on B that *starts* that long after an event
    on A *ends* links to it.
    """

    OVERLAP = "overlap"
    TRANSIT = "transit"


class TopologyEdge(Base):
    """`core.topology_edges` — the camera graph the correlation service (P3-J2)
    links events across. Field names match `TopologyEdgeInternal`
    (`vms_common.contracts.topology`), the shape `GET /internal/v1/topology` returns.

    The table refuses a malformed edge itself, not just the API: an overlap edge
    carries only `tolerance_s` and is always bidirectional (overlap is symmetric);
    a transit edge carries only a `min_s..max_s` window; a camera never links to
    itself; and a given directed pair has at most one edge of each type.
    """

    __tablename__ = "topology_edges"
    __table_args__ = (
        CheckConstraint("from_camera_id <> to_camera_id", name="distinct_cameras"),
        CheckConstraint(
            "(edge_type = 'overlap' AND tolerance_s IS NOT NULL AND tolerance_s >= 0"
            " AND min_s IS NULL AND max_s IS NULL AND bidirectional)"
            " OR (edge_type = 'transit' AND tolerance_s IS NULL"
            " AND min_s IS NOT NULL AND max_s IS NOT NULL AND min_s >= 0 AND max_s >= min_s)",
            name="edge_parameters",
        ),
        UniqueConstraint(
            "from_camera_id", "to_camera_id", "edge_type", name="uq_topology_edges_pair"
        ),
        # Overlap is symmetric, so A->B and B->A are the same edge: one row per unordered pair.
        Index(
            "uq_topology_edges_overlap_pair",
            func.least(text("from_camera_id"), text("to_camera_id")),
            func.greatest(text("from_camera_id"), text("to_camera_id")),
            unique=True,
            postgresql_where=text("edge_type = 'overlap'"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    from_camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    edge_type: Mapped[EdgeType] = mapped_column(
        Enum(
            EdgeType,
            name="edge_type",
            schema=SCHEMA,
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    min_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    tolerance_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    bidirectional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    """`core.audit_log` — append-only; written for auth and user-management
    events (FR-AUTH-04) and extended as more actions land.
    """

    __tablename__ = "audit_log"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
