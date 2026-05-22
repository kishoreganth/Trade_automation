"""Add announcement_insights table for AI-extracted investor presentation and monthly update data.

Revision ID: 007
Revises: 006
Create Date: 2026-05-22
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcement_insights",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("stock_symbol", sa.String, nullable=False),
        sa.Column("company_name", sa.String),
        sa.Column("quarter", sa.String, nullable=False),
        sa.Column("financial_year", sa.String, nullable=False),
        sa.Column("announcement_type", sa.String, nullable=False),
        sa.Column("source_pdf_url", sa.String),
        sa.Column("source_message_id", sa.Integer, sa.ForeignKey("messages.id")),
        sa.Column("exchange", sa.String, server_default="BSE"),

        # Financial metrics
        sa.Column("revenue", sa.Float),
        sa.Column("revenue_unit", sa.String),
        sa.Column("ebitda", sa.Float),
        sa.Column("ebitda_margin_pct", sa.Float),
        sa.Column("pat", sa.Float),
        sa.Column("pat_margin_pct", sa.Float),
        sa.Column("eps_basic", sa.Float),
        sa.Column("eps_diluted", sa.Float),
        sa.Column("roce_pct", sa.Float),
        sa.Column("roe_pct", sa.Float),
        sa.Column("debt_to_equity", sa.Float),
        sa.Column("working_capital_days", sa.Float),
        sa.Column("free_cash_flow", sa.Float),
        sa.Column("order_book_value", sa.Float),
        sa.Column("dividend_per_share", sa.Float),
        sa.Column("dividend_payout_ratio", sa.Float),
        sa.Column("capex_current_year", sa.Float),
        sa.Column("capex_planned_next", sa.Float),
        sa.Column("revenue_guidance_low", sa.Float),
        sa.Column("revenue_guidance_high", sa.Float),
        sa.Column("export_share_pct", sa.Float),
        sa.Column("domestic_share_pct", sa.Float),
        sa.Column("yoy_revenue_growth_pct", sa.Float),
        sa.Column("qoq_revenue_growth_pct", sa.Float),
        sa.Column("capacity_utilization_pct", sa.Float),

        # Segment / business breakdown (JSON)
        sa.Column("segment_revenue", sa.Text),
        sa.Column("geography_split", sa.Text),
        sa.Column("product_mix", sa.Text),
        sa.Column("customer_concentration", sa.Text),

        # Forward-looking / predictions
        sa.Column("revenue_growth_guidance", sa.Text),
        sa.Column("margin_signal", sa.String),
        sa.Column("industry_tailwinds", sa.Text),
        sa.Column("industry_headwinds", sa.Text),
        sa.Column("management_priorities", sa.Text),
        sa.Column("capex_timeline", sa.Text),
        sa.Column("new_market_entries", sa.Text),
        sa.Column("hiring_plans", sa.Text),

        # Qualitative assessment
        sa.Column("management_outlook", sa.String),
        sa.Column("management_confidence", sa.Integer),
        sa.Column("competitive_moat", sa.Text),
        sa.Column("esg_highlights", sa.Text),
        sa.Column("key_risks", sa.Text),
        sa.Column("growth_drivers", sa.Text),
        sa.Column("next_quarter_outlook", sa.String),

        # AI-generated summaries
        sa.Column("executive_summary", sa.Text),
        sa.Column("investment_thesis", sa.Text),
        sa.Column("key_takeaways", sa.Text),
        sa.Column("next_quarter_prediction", sa.Text),
        sa.Column("bull_case", sa.Text),
        sa.Column("bear_case", sa.Text),

        # Metadata
        sa.Column("raw_ai_response", sa.Text),
        sa.Column("extraction_mode", sa.String),
        sa.Column("pages_processed", sa.Integer),
        sa.Column("extraction_status", sa.String, server_default="pending"),
        sa.Column("extraction_error", sa.Text),
        sa.Column("announcement_date", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.UniqueConstraint("stock_symbol", "quarter", "financial_year", "announcement_type", "source_pdf_url",
                            name="uq_ann_insight_sym_q_fy_type_pdf"),
    )
    op.create_index("idx_ann_insight_symbol", "announcement_insights", ["stock_symbol"])
    op.create_index("idx_ann_insight_status", "announcement_insights", ["extraction_status"])
    op.create_index("idx_ann_insight_type", "announcement_insights", ["announcement_type"])
    op.create_index("idx_ann_insight_msg_id", "announcement_insights", ["source_message_id"])


def downgrade() -> None:
    op.drop_table("announcement_insights")
