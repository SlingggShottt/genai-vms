"""ORM models for every domain schema, imported here so Alembic's
autogenerate can discover them through `Base.metadata`
(design_architecture.md §6.1).
"""

from __future__ import annotations

from vms_db.models.core import AuditLog, Camera, RefreshToken, User, UserRole

__all__ = ["AuditLog", "Camera", "RefreshToken", "User", "UserRole"]
