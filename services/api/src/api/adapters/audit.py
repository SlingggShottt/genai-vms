"""Audit log repository — append-only writes to `core.audit_log`
(FR-AUTH-04; P1-J2 AC: audit entries for login and user changes).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_db.models import AuditLog
from vms_db.session import session_scope


async def write_audit_log(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Write one audit entry in its own committed transaction, independent
    of the caller's request transaction. An audit entry must survive even
    when the surrounding handler goes on to raise/roll back (e.g. a failed
    login) — a request-scoped session (`api.api.deps.get_session`) rolls
    back its entire transaction, flushed-but-uncommitted audit rows
    included, on any exception, which a write on the caller's own session
    can't survive. The tradeoff is a second DB connection/transaction per
    audited action; acceptable at this project's scale for the correctness
    guarantee.
    """
    async with session_scope(session_factory) as session:
        session.add(
            AuditLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
                ip_address=ip_address,
            )
        )
