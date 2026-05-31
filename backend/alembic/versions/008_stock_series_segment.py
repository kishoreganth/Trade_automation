"""Add series, market_segment, and identity columns to stocks table.

Revision ID: 008
Revises: 007
Create Date: 2026-05-31
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    columns = [c["name"] for c in sa_inspect(bind).get_columns(table)]
    return column in columns


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = :name"
    ), {"name": index_name})
    return result.fetchone() is not None


def upgrade() -> None:
    new_cols = [
        "nse_symbol", "bse_scrip_code", "nse_series",
        "bse_series", "market_segment", "industry_group",
    ]
    for col in new_cols:
        if not _column_exists("stocks", col):
            op.add_column("stocks", sa.Column(col, sa.String, nullable=True))

    if not _index_exists("idx_stocks_isin"):
        op.create_index("idx_stocks_isin", "stocks", ["isin"])
    if not _index_exists("idx_stocks_nse_symbol"):
        op.create_index("idx_stocks_nse_symbol", "stocks", ["nse_symbol"])
    if not _index_exists("idx_stocks_market_segment"):
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
