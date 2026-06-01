"""Add reviewed_at timestamp to quarterly_results.

Tracks the exact moment a PE Pending row is moved to PE Reviewed.
Backfills existing reviewed rows using updated_at as approximation.

Revision ID: 010
Revises: 009
Create Date: 2026-06-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    columns = [c["name"] for c in sa_inspect(bind).get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _column_exists("quarterly_results", "reviewed_at"):
        op.add_column(
            "quarterly_results",
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )

    # Backfill: set reviewed_at = updated_at for rows already reviewed.
    # This is a best-effort approximation for historical data.
    op.execute(sa.text("""
        UPDATE quarterly_results
        SET reviewed_at = updated_at
        WHERE valuation IS NOT NULL AND valuation != ''
          AND reviewed_at IS NULL
    """))


def downgrade() -> None:
    if _column_exists("quarterly_results", "reviewed_at"):
        op.drop_column("quarterly_results", "reviewed_at")
