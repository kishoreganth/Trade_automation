"""Add series, market_segment, and identity columns to stocks table.

Revision ID: 008
Revises: 007
Create Date: 2026-05-31
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stocks", sa.Column("nse_symbol", sa.String, nullable=True))
    op.add_column("stocks", sa.Column("bse_scrip_code", sa.String, nullable=True))
    op.add_column("stocks", sa.Column("nse_series", sa.String, nullable=True))
    op.add_column("stocks", sa.Column("bse_series", sa.String, nullable=True))
    op.add_column("stocks", sa.Column("market_segment", sa.String, nullable=True))
    op.add_column("stocks", sa.Column("industry_group", sa.String, nullable=True))

    op.create_index("idx_stocks_isin", "stocks", ["isin"], unique=True)
    op.create_index("idx_stocks_nse_symbol", "stocks", ["nse_symbol"])
    op.create_index("idx_stocks_market_segment", "stocks", ["market_segment"])


def downgrade() -> None:
    op.drop_index("idx_stocks_market_segment", table_name="stocks")
    op.drop_index("idx_stocks_nse_symbol", table_name="stocks")
    op.drop_index("idx_stocks_isin", table_name="stocks")

    op.drop_column("stocks", "industry_group")
    op.drop_column("stocks", "market_segment")
    op.drop_column("stocks", "bse_series")
    op.drop_column("stocks", "nse_series")
    op.drop_column("stocks", "bse_scrip_code")
    op.drop_column("stocks", "nse_symbol")
