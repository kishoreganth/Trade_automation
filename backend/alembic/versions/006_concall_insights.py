"""Add concall_insights table for AI-extracted conference call data.

Revision ID: 006
Revises: 005
Create Date: 2026-05-22
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "concall_insights",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("stock_symbol", sa.String, nullable=False),
        sa.Column("company_name", sa.String),
        sa.Column("quarter", sa.String, nullable=False),
        sa.Column("financial_year", sa.String, nullable=False),
        sa.Column("source_pdf_url", sa.String),
        sa.Column("source_message_id", sa.Integer, sa.ForeignKey("messages.id")),
        sa.Column("exchange", sa.String, server_default="BSE"),

        # Quantitative metrics
        sa.Column("revenue_mentioned", sa.Float),
        sa.Column("revenue_unit", sa.String),
        sa.Column("ebitda_margin_pct", sa.Float),
        sa.Column("pat_margin_pct", sa.Float),
        sa.Column("capacity_utilization_pct", sa.Float),
        sa.Column("capex_current_year", sa.Float),
        sa.Column("capex_planned_next", sa.Float),
        sa.Column("revenue_guidance_low", sa.Float),
        sa.Column("revenue_guidance_high", sa.Float),
        sa.Column("export_share_pct", sa.Float),
        sa.Column("market_share_pct", sa.Float),
        sa.Column("technical_fee_pct", sa.Float),
        sa.Column("industry_volume", sa.Float),
        sa.Column("yoy_revenue_growth_pct", sa.Float),
        sa.Column("qoq_revenue_growth_pct", sa.Float),

        # Qualitative signals
        sa.Column("management_outlook", sa.String),
        sa.Column("next_quarter_outlook", sa.String),
        sa.Column("management_confidence", sa.Integer),
        sa.Column("growth_drivers", sa.Text),
        sa.Column("key_risks", sa.Text),
        sa.Column("new_products", sa.Text),
        sa.Column("expansion_plans", sa.Text),
        sa.Column("margin_levers", sa.Text),
        sa.Column("competitive_position", sa.Text),
        sa.Column("customer_updates", sa.Text),
        sa.Column("sector_trends", sa.Text),

        # AI-generated summaries
        sa.Column("executive_summary", sa.Text),
        sa.Column("investment_thesis", sa.Text),
        sa.Column("key_takeaways", sa.Text),

        # Metadata
        sa.Column("raw_ai_response", sa.Text),
        sa.Column("transcript_length", sa.Integer),
        sa.Column("extraction_status", sa.String, server_default="pending"),
        sa.Column("extraction_error", sa.Text),
        sa.Column("announcement_date", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.UniqueConstraint("stock_symbol", "quarter", "financial_year", "source_pdf_url",
                            name="uq_concall_symbol_q_fy_pdf"),
    )
    op.create_index("idx_concall_symbol", "concall_insights", ["stock_symbol"])
    op.create_index("idx_concall_status", "concall_insights", ["extraction_status"])
    op.create_index("idx_concall_quarter_fy", "concall_insights", ["quarter", "financial_year"])
    op.create_index("idx_concall_msg_id", "concall_insights", ["source_message_id"])


def downgrade() -> None:
    op.drop_table("concall_insights")
