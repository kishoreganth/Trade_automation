"""Performance indexes: covering index for quarterly_results bulk EPS queries.

Revision ID: 003
Revises: 002
Create Date: 2026-05-10
"""
from typing import Sequence, Union
from alembic import op


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_qr_quarters_cover ON quarterly_results(
            stock_symbol, financial_year, quarter,
            eps_diluted_consolidated, eps_basic_consolidated,
            eps_diluted_standalone, eps_basic_standalone,
            cumulative_eps_diluted_consolidated, cumulative_eps_basic_consolidated,
            cumulative_eps_diluted_standalone, cumulative_eps_basic_standalone
        )
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_qr_quarters_cover")
