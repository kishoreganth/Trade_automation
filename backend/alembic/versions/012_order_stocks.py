"""Create order_stocks table for place-order Postgres mode.

Replaces Google Sheet 'place_order_v2' tab.  The nse_cm_neo formula
(STOCK_NAME / EXCHANGE_TOKEN lookup) is handled via JOIN with the
existing stocks table at query time.

Revision ID: 012
Revises: 011
Create Date: 2026-06-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order_stocks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("gap", sa.Numeric(10, 2), nullable=False, server_default="3"),
        sa.Column("market", sa.String, nullable=False, server_default="nse_cm"),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("open_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("buy_order", sa.Numeric(12, 2), nullable=True),
        sa.Column("sell_order", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_order_stocks_symbol", "order_stocks", ["symbol"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_order_stocks_symbol", table_name="order_stocks")
    op.drop_table("order_stocks")
