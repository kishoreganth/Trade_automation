"""Create pe_audit_log table for tracking all PE review actions.

Records every valuation change, bulk ignore, and field update with
before/after snapshots so we can forensically determine whether an action
was attempted vs forgotten.

Revision ID: 011
Revises: 010
Create Date: 2026-06-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pe_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("stock_symbol", sa.String, nullable=False),
        sa.Column("row_id", sa.Integer, nullable=True),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("old_valuation", sa.String, nullable=True),
        sa.Column("new_valuation", sa.String, nullable=True),
        sa.Column("old_fields", sa.JSON, nullable=True),
        sa.Column("new_fields", sa.JSON, nullable=True),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("request_id", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("idx_audit_symbol", "pe_audit_log", ["stock_symbol"])
    op.create_index("idx_audit_created", "pe_audit_log", ["created_at"])
    op.create_index("idx_audit_symbol_date", "pe_audit_log", ["stock_symbol", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_symbol_date", table_name="pe_audit_log")
    op.drop_index("idx_audit_created", table_name="pe_audit_log")
    op.drop_index("idx_audit_symbol", table_name="pe_audit_log")
    op.drop_table("pe_audit_log")
