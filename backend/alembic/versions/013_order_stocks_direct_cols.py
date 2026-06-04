"""Add stock_name and exchange_token columns to order_stocks.

Stores Kotak master scrip data directly in order_stocks so the table
is self-contained without depending on the stocks table JOIN.

Revision ID: 013
Revises: 012
Create Date: 2026-06-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    columns = [c["name"] for c in sa_inspect(bind).get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _column_exists("order_stocks", "stock_name"):
        op.add_column("order_stocks", sa.Column("stock_name", sa.String, nullable=True))
    if not _column_exists("order_stocks", "exchange_token"):
        op.add_column("order_stocks", sa.Column("exchange_token", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("order_stocks", "exchange_token")
    op.drop_column("order_stocks", "stock_name")
