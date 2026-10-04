"""ORM models for every domain schema, imported here so Alembic's
autogenerate can discover them through `Base.metadata`
(design_architecture.md §6.1).
"""

from __future__ import annotations

from vms_db.models.core import (
    AuditLog,
    Camera,
    EdgeType,
    RefreshToken,
    TopologyEdge,
    User,
    UserRole,
    Zone,
    ZoneType,
)
from vms_db.models.correlation import CorrelationGroup, CorrelationLinkRow
from vms_db.models.events import Candidate
from vms_db.models.media import Segment
from vms_db.models.vision import MinuteCount, Track, TrackSegment

__all__ = [
    "AuditLog",
    "Camera",
    "Candidate",
    "CorrelationGroup",
    "CorrelationLinkRow",
    "EdgeType",
    "MinuteCount",
    "RefreshToken",
    "Segment",
    "TopologyEdge",
    "Track",
    "TrackSegment",
    "User",
    "UserRole",
    "Zone",
    "ZoneType",
]
