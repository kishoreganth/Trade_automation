"""Normalize announcement_date to IST midnight for consistent dedup.

The unique constraint (stock_symbol, quarter, financial_year, announcement_date)
was being bypassed because BSE returns the same result announcement at slightly
different times (e.g. 1:54 PM vs 1:56 PM) from different API categories.
Truncating to date-only (IST midnight) ensures duplicates are caught.

Steps:
  1. Merge duplicate rows that share the same (symbol, quarter, fy, IST date)
     — keep the best row (completed > pending, valuation set > null, highest id).
  2. Truncate all remaining announcement_dates to IST midnight.

Revision ID: 005
Revises: 004
Create Date: 2026-05-14
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Delete duplicate rows, keeping the best one per
    # (stock_symbol, quarter, financial_year, IST calendar date).
    # Priority: completed status > others, valuation set > null, highest id.
    conn.execute(text("""
        DELETE FROM quarterly_results
        WHERE id NOT IN (
            SELECT DISTINCT ON (
                stock_symbol,
                quarter,
                financial_year,
                COALESCE(
                    DATE(announcement_date AT TIME ZONE 'Asia/Kolkata'),
                    '1970-01-01'
                )
            ) id
            FROM quarterly_results
            ORDER BY
                stock_symbol,
                quarter,
                financial_year,
                COALESCE(
                    DATE(announcement_date AT TIME ZONE 'Asia/Kolkata'),
                    '1970-01-01'
                ),
                CASE WHEN extraction_status = 'completed' THEN 0 ELSE 1 END,
                CASE WHEN valuation IS NOT NULL AND valuation != '' THEN 0 ELSE 1 END,
                id DESC
        )
    """))

    # Step 2: Normalize all announcement_dates to IST midnight.
    conn.execute(text("""
        UPDATE quarterly_results
        SET announcement_date = DATE(
            announcement_date AT TIME ZONE 'Asia/Kolkata'
        ) AT TIME ZONE 'Asia/Kolkata'
        WHERE announcement_date IS NOT NULL
    """))


def downgrade() -> None:
    pass
