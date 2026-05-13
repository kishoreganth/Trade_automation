"""Fix BSE rows: convert numeric scrip codes in stock_symbol to NSE trading symbols.

Revision ID: 004
Revises: 003
Create Date: 2026-05-13
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Update stock_symbol from scrip code to NSE symbol where possible
    conn.execute(text("""
        UPDATE quarterly_results qr
        SET stock_symbol = s.symbol
        FROM stocks s
        WHERE qr.stock_symbol ~ '^\\d+$'
          AND s.bse_token = CAST(qr.stock_symbol AS INT)
          AND NOT EXISTS (
              SELECT 1 FROM quarterly_results dup
              WHERE dup.stock_symbol = s.symbol
                AND dup.quarter = qr.quarter
                AND dup.financial_year = qr.financial_year
                AND dup.announcement_date = qr.announcement_date
          )
    """))

    # Step 2: Delete BSE duplicates that conflict with existing NSE rows
    # (keep the NSE row since it already has the correct symbol)
    conn.execute(text("""
        DELETE FROM quarterly_results qr
        USING stocks s, quarterly_results keep
        WHERE qr.stock_symbol ~ '^\\d+$'
          AND s.bse_token = CAST(qr.stock_symbol AS INT)
          AND keep.stock_symbol = s.symbol
          AND keep.quarter = qr.quarter
          AND keep.financial_year = qr.financial_year
          AND keep.announcement_date = qr.announcement_date
    """))


def downgrade() -> None:
    pass
