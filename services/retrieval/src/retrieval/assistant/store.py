"""Assistant memory in Postgres (design §10.3): sessions, messages, and the rolling summary."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.ids import uuid7_str
from vms_db.models import ChatMessage, ChatSession

WINDOW = 12  # messages kept verbatim; older ones live in the summary


@dataclass(frozen=True)
class Turn:
    role: str
    content: str


class ChatStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, user_id: uuid.UUID) -> ChatSession:
        row = ChatSession(id=uuid.UUID(uuid7_str()), user_id=user_id)
        async with self._sessions() as s, s.begin():
            s.add(row)
        return row

    async def list(self, user_id: uuid.UUID, limit: int = 30) -> list[ChatSession]:
        async with self._sessions() as s:
            return list(
                (
                    await s.execute(
                        select(ChatSession)
                        .where(ChatSession.user_id == user_id)
                        .order_by(ChatSession.updated_at.desc())
                        .limit(limit)
                    )
                ).scalars()
            )

    async def get(self, session_id: uuid.UUID, user_id: uuid.UUID) -> ChatSession | None:
        async with self._sessions() as s:
            row = await s.get(ChatSession, session_id)
        return row if row is not None and row.user_id == user_id else None

    async def delete(self, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        async with self._sessions() as s, s.begin():
            res = await s.execute(
                delete(ChatSession).where(
                    ChatSession.id == session_id, ChatSession.user_id == user_id
                )
            )
        return res.rowcount > 0

    async def messages(self, session_id: uuid.UUID) -> list[ChatMessage]:
        async with self._sessions() as s:
            return list(
                (
                    await s.execute(
                        select(ChatMessage)
                        .where(ChatMessage.session_id == session_id)
                        .order_by(ChatMessage.created_at, ChatMessage.id)
                    )
                ).scalars()
            )

    async def add(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        *,
        citations: list | None = None,
        tools: list | None = None,
        status: str = "complete",
    ) -> uuid.UUID:
        mid = uuid.UUID(uuid7_str())
        async with self._sessions() as s, s.begin():
            s.add(
                ChatMessage(
                    id=mid,
                    session_id=session_id,
                    role=role,
                    content=content,
                    citations=citations or [],
                    tools=tools or [],
                    status=status,
                )
            )
            await s.execute(
                update(ChatSession)
                .where(ChatSession.id == session_id)
                .values(updated_at=func.now())
            )
        return mid

    async def set_title(self, session_id: uuid.UUID, title: str) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                update(ChatSession).where(ChatSession.id == session_id).values(title=title[:80])
            )

    async def set_summary(self, session_id: uuid.UUID, summary: str, covered: int) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                update(ChatSession)
                .where(ChatSession.id == session_id)
                .values(
                    summary=summary, summarized_count=covered, updated_at=ChatSession.updated_at
                )
            )


def split_history(messages: list[ChatMessage]) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """(older messages the summary should cover, the last `WINDOW` kept verbatim)."""
    return messages[:-WINDOW] if len(messages) > WINDOW else [], messages[-WINDOW:]


def render_history(messages: list[ChatMessage], *, per_message: int = 500) -> str:
    return "\n".join(
        f"{'Operator' if m.role == 'user' else 'Assistant'}: {m.content[:per_message]}"
        for m in messages
        if m.status != "failed"
    )
