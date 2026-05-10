"""Initial schema - all tables from SQLite migration

Revision ID: 001
Revises: None
Create Date: 2026-05-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.String, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("symbol", sa.String),
        sa.Column("company_name", sa.String),
        sa.Column("description", sa.Text),
        sa.Column("file_url", sa.String),
        sa.Column("raw_message", sa.Text),
        sa.Column("option", sa.String),
        sa.Column("sector", sa.String),
        sa.Column("exchange", sa.String, server_default="NSE"),
    )
    op.create_index("idx_messages_timestamp", "messages", ["timestamp"])
    op.create_index("idx_messages_symbol", "messages", ["symbol"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String, unique=True, nullable=False),
        sa.Column("password_hash", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_token", sa.String, unique=True, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_sessions_token", "sessions", ["session_token"])

    op.create_table(
        "scheduled_fetch_config",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("hour", sa.Integer, nullable=False, server_default=sa.text("12")),
        sa.Column("minute", sa.Integer, nullable=False, server_default=sa.text("40")),
        sa.Column("second", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("weekdays_only", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String, unique=True, nullable=False),
        sa.Column("company_name", sa.String),
        sa.Column("exchange", sa.String),
        sa.Column("sector", sa.String),
        sa.Column("sub_sector", sa.String),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("nse_token", sa.Integer),
        sa.Column("bse_token", sa.Integer),
        sa.Column("isin", sa.String),
    )
    op.create_index("idx_stocks_symbol", "stocks", ["symbol"])
    op.create_index("idx_stocks_sector", "stocks", ["sector"])

    op.create_table(
        "quarterly_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("stock_symbol", sa.String, nullable=False),
        sa.Column("company_name", sa.String),
        sa.Column("quarter", sa.String, nullable=False),
        sa.Column("financial_year", sa.String, nullable=False),
        sa.Column("period_ended", sa.String),
        sa.Column("eps_basic_standalone", sa.Float),
        sa.Column("eps_diluted_standalone", sa.Float),
        sa.Column("eps_basic_consolidated", sa.Float),
        sa.Column("eps_diluted_consolidated", sa.Float),
        sa.Column("fy_eps_basic_standalone", sa.Float),
        sa.Column("fy_eps_diluted_standalone", sa.Float),
        sa.Column("fy_eps_basic_consolidated", sa.Float),
        sa.Column("fy_eps_diluted_consolidated", sa.Float),
        sa.Column("fy_eps_formula_standalone", sa.Text),
        sa.Column("fy_eps_formula_consolidated", sa.Text),
        sa.Column("standalone_data", sa.Text),
        sa.Column("consolidated_data", sa.Text),
        sa.Column("raw_ai_response", sa.Text),
        sa.Column("source_pdf_url", sa.String),
        sa.Column("source_message_id", sa.Integer, sa.ForeignKey("messages.id")),
        sa.Column("exchange", sa.String),
        sa.Column("units", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("announcement_date", sa.DateTime(timezone=True)),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id")),
        sa.Column("cmp", sa.Float),
        sa.Column("pe", sa.Float),
        sa.Column("cmp_updated_at", sa.DateTime(timezone=True)),
        sa.Column("cumulative_eps_basic_standalone", sa.Float),
        sa.Column("cumulative_eps_diluted_standalone", sa.Float),
        sa.Column("cumulative_eps_basic_consolidated", sa.Float),
        sa.Column("cumulative_eps_diluted_consolidated", sa.Float),
        sa.Column("valuation", sa.String),
        sa.Column("comments", sa.Text),
        sa.Column("extraction_status", sa.String, server_default="completed"),
        sa.Column("extraction_error", sa.Text),
        sa.Column("source_pdf_url_tracking", sa.String),
        sa.Column("recommendation", sa.String),
        sa.Column("target_price", sa.Float),
        sa.Column("manual_fy_eps", sa.Float),
        sa.Column("manual_fy_eps_formula", sa.String),
        sa.UniqueConstraint("stock_symbol", "quarter", "financial_year", "announcement_date",
                            name="uq_qr_symbol_quarter_fy_date"),
    )
    op.create_index("idx_qr_symbol", "quarterly_results", ["stock_symbol"])
    op.create_index("idx_qr_quarter_fy", "quarterly_results", ["quarter", "financial_year"])
    op.create_index("idx_qr_stock_id", "quarterly_results", ["stock_id"])
    op.create_index("idx_qr_extraction_status", "quarterly_results", ["extraction_status"])
    op.create_index("idx_qr_sym_fy_q", "quarterly_results", ["stock_symbol", "financial_year", "quarter"])
    op.create_index("idx_qr_valuation", "quarterly_results", ["valuation"])
    op.create_index("idx_qr_created_at", "quarterly_results", ["created_at"])
    op.create_index("idx_qr_quarter_val", "quarterly_results", ["quarter", "valuation"])

    op.create_table(
        "failed_extractions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("stock_symbol", sa.String, nullable=False),
        sa.Column("pdf_url", sa.String),
        sa.Column("exchange", sa.String),
        sa.Column("announcement_date", sa.String),
        sa.Column("error_message", sa.Text),
        sa.Column("attempts", sa.Integer, server_default=sa.text("1")),
        sa.Column("status", sa.String, server_default="failed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "pe_formulas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String, unique=True, nullable=False),
        sa.Column("q1_expr", sa.String, nullable=False, server_default="Q1*4"),
        sa.Column("q2_expr", sa.String, nullable=False, server_default="(Q1+Q2)*2"),
        sa.Column("q3_expr", sa.String, nullable=False, server_default="(Q1+Q2+Q3)*4/3"),
        sa.Column("q4_expr", sa.String, nullable=False, server_default="FY"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sector_formulas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("sector", sa.String, nullable=False),
        sa.Column("sub_sector", sa.String, server_default=""),
        sa.Column("quarter", sa.String, nullable=False),
        sa.Column("formula_expr", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("sector", "sub_sector", "quarter", name="uq_sector_subsector_quarter"),
    )

    op.create_table(
        "bse_announcements_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scrip_code", sa.String, nullable=False),
        sa.Column("company_name", sa.String),
        sa.Column("announcement_type", sa.String, nullable=False),
        sa.Column("announcement_date", sa.String, nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("pdf_url", sa.String),
        sa.Column("xml_url", sa.String),
        sa.Column("exchange", sa.String, server_default="BSE"),
        sa.Column("processed", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("scrip_code", "announcement_type", "pdf_url", name="uq_bse_scrip_type_pdf"),
    )
    op.create_index("idx_bse_log_scrip_date", "bse_announcements_log", ["scrip_code", "announcement_date"])
    op.create_index("idx_bse_log_processed", "bse_announcements_log", ["processed"])

    # Seed default PE formula
    op.execute("""
        INSERT INTO pe_formulas (name, q1_expr, q2_expr, q3_expr, q4_expr, is_default, created_at, updated_at)
        VALUES ('Default', 'Q1*4', '(Q1+Q2)*2', '(Q1+Q2+Q3)*4/3', 'FY', true, NOW(), NOW())
        ON CONFLICT (name) DO NOTHING
    """)

    # Seed default scheduled_fetch_config
    op.execute("""
        INSERT INTO scheduled_fetch_config (enabled, hour, minute, second, weekdays_only, updated_at)
        VALUES (true, 12, 40, 0, true, NOW())
    """)


def downgrade() -> None:
    op.drop_table("bse_announcements_log")
    op.drop_table("sector_formulas")
    op.drop_table("pe_formulas")
    op.drop_table("failed_extractions")
    op.drop_table("quarterly_results")
    op.drop_table("stocks")
    op.drop_table("scheduled_fetch_config")
    op.drop_table("sessions")
    op.drop_table("users")
    op.drop_table("messages")
