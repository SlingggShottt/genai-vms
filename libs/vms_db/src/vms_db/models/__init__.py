"""ORM models for every domain schema, imported here so Alembic's
autogenerate can discover them through `Base.metadata`
(design_architecture.md §6.1).
"""

from __future__ import annotations

from vms_db.models.cases import Case, CaseItem
from vms_db.models.core import (
    Alert,
    AlertStatus,
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
from vms_db.models.events import Candidate, Event
from vms_db.models.media import Segment
from vms_db.models.reasoning import DailyReport, Incident, ReasoningJob
from vms_db.models.retrieval import ChatMessage, ChatSession, SearchLog
from vms_db.models.vision import MinuteCount, Track, TrackSegment

__all__ = [
    "Alert",
    "AlertStatus",
    "AuditLog",
    "Camera",
    "Case",
    "CaseItem",
    "ChatMessage",
    "ChatSession",
    "Candidate",
    "CorrelationGroup",
    "CorrelationLinkRow",
    "DailyReport",
    "EdgeType",
    "Event",
    "Incident",
    "MinuteCount",
    "ReasoningJob",
    "RefreshToken",
    "SearchLog",
    "Segment",
    "TopologyEdge",
    "Track",
    "TrackSegment",
    "User",
    "UserRole",
    "Zone",
    "ZoneType",
]
