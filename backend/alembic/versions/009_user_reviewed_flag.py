"""Add user_reviewed flag to quarterly_results.

Allows users to move rows to PE Reviewed immediately (even while
extraction is still processing) without altering extraction_status.

Revision ID: 009
Revises: 008
Create Date: 2026-05-31
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    columns = [c["name"] for c in sa_inspect(bind).get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _column_exists("quarterly_results", "user_reviewed"):
        op.add_column(
            "quarterly_results",
            sa.Column("user_reviewed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        )

    # Backfill: any row that already has a valuation (i.e. was reviewed)
    # should be marked user_reviewed = TRUE so it keeps appearing on
    # PE Reviewed regardless of extraction_status.
    op.execute(sa.text("""
        UPDATE quarterly_results
        SET user_reviewed = TRUE
        WHERE valuation IS NOT NULL AND valuation != ''
          AND user_reviewed = FALSE
    """))


def downgrade() -> None:
    if _column_exists("quarterly_results", "user_reviewed"):
        op.drop_column("quarterly_results", "user_reviewed")
