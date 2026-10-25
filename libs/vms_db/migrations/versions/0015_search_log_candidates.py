"""retrieval: the candidates a search had before reranking, kept in its log

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "search_logs",
        sa.Column(
            "candidates", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        schema="retrieval",
    )


def downgrade() -> None:
    op.drop_column("search_logs", "candidates", schema="retrieval")
