"""retrieval schema: jit_cache

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jit_cache",
        sa.Column("segment_id", sa.String(length=200), nullable=False),
        sa.Column("question_hash", sa.String(length=40), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("keyframe_uri", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("segment_id", "question_hash", name=op.f("pk_jit_cache")),
        schema="retrieval",
    )


def downgrade() -> None:
    op.drop_table("jit_cache", schema="retrieval")
