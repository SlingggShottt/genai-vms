"""reasoning: where the PDF of an incident report and of a daily report is stored

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("pdf_uri", sa.Text(), nullable=True), schema="reasoning")
    op.add_column(
        "daily_reports", sa.Column("pdf_uri", sa.Text(), nullable=True), schema="reasoning"
    )


def downgrade() -> None:
    op.drop_column("daily_reports", "pdf_uri", schema="reasoning")
    op.drop_column("incidents", "pdf_uri", schema="reasoning")
