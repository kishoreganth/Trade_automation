from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, Text,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.sql import func
from ..database import Base


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, unique=True, nullable=False, index=True)
    company_name = Column(String)
    exchange = Column(String)
    sector = Column(String, index=True)
    sub_sector = Column(String)
    is_active = Column(Boolean, nullable=False, default=True)
    added_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    nse_token = Column(Integer)
    bse_token = Column(Integer)
    isin = Column(String, unique=True)
    nse_symbol = Column(String)
    bse_scrip_code = Column(String)
    nse_series = Column(String)
    bse_series = Column(String)
    market_segment = Column(String, index=True)
    industry_group = Column(String)


class QuarterlyResult(Base):
    __tablename__ = "quarterly_results"
    __table_args__ = (
        UniqueConstraint("stock_symbol", "quarter", "financial_year", "announcement_date",
                         name="uq_qr_symbol_quarter_fy_date"),
        Index("idx_qr_symbol", "stock_symbol"),
        Index("idx_qr_quarter_fy", "quarter", "financial_year"),
        Index("idx_qr_extraction_status", "extraction_status"),
        Index("idx_qr_sym_fy_q", "stock_symbol", "financial_year", "quarter"),
        Index("idx_qr_valuation", "valuation"),
        Index("idx_qr_created_at", "created_at"),
        Index("idx_qr_quarter_val", "quarter", "valuation"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_symbol = Column(String, nullable=False)
    company_name = Column(String)
    quarter = Column(String, nullable=False)
    financial_year = Column(String, nullable=False)
    period_ended = Column(String)

    eps_basic_standalone = Column(Float)
    eps_diluted_standalone = Column(Float)
    eps_basic_consolidated = Column(Float)
    eps_diluted_consolidated = Column(Float)

    fy_eps_basic_standalone = Column(Float)
    fy_eps_diluted_standalone = Column(Float)
    fy_eps_basic_consolidated = Column(Float)
    fy_eps_diluted_consolidated = Column(Float)
    fy_eps_formula_standalone = Column(Text)
    fy_eps_formula_consolidated = Column(Text)

    standalone_data = Column(Text)
    consolidated_data = Column(Text)
    raw_ai_response = Column(Text)

    source_pdf_url = Column(String)
    source_message_id = Column(Integer, ForeignKey("messages.id"))
    exchange = Column(String)
    units = Column(String)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    announcement_date = Column(DateTime(timezone=True))

    stock_id = Column(Integer, ForeignKey("stocks.id"))
    cmp = Column(Float)
    pe = Column(Float)
    cmp_updated_at = Column(DateTime(timezone=True))

    cumulative_eps_basic_standalone = Column(Float)
    cumulative_eps_diluted_standalone = Column(Float)
    cumulative_eps_basic_consolidated = Column(Float)
    cumulative_eps_diluted_consolidated = Column(Float)

    valuation = Column(String)
    comments = Column(Text)
    extraction_status = Column(String, default="completed")
    extraction_error = Column(Text)
    source_pdf_url_tracking = Column(String)
    recommendation = Column(String)
    target_price = Column(Float)
    manual_fy_eps = Column(Float)
    manual_fy_eps_formula = Column(String)


class FailedExtraction(Base):
    __tablename__ = "failed_extractions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_symbol = Column(String, nullable=False)
    pdf_url = Column(String)
    exchange = Column(String)
    announcement_date = Column(String)
    error_message = Column(Text)
    attempts = Column(Integer, default=1)
    status = Column(String, default="failed")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))


class PEFormula(Base):
    __tablename__ = "pe_formulas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    q1_expr = Column(String, nullable=False, default="Q1*4")
    q2_expr = Column(String, nullable=False, default="(Q1+Q2)*2")
    q3_expr = Column(String, nullable=False, default="(Q1+Q2+Q3)*4/3")
    q4_expr = Column(String, nullable=False, default="FY")
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SectorFormula(Base):
    __tablename__ = "sector_formulas"
    __table_args__ = (
        UniqueConstraint("sector", "sub_sector", "quarter", name="uq_sector_subsector_quarter"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector = Column(String, nullable=False)
    sub_sector = Column(String, default="")
    quarter = Column(String, nullable=False)
    formula_expr = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CustomValuation(Base):
    """User-defined valuation remarks (in addition to canonical 6 in app/constants.py)."""
    __tablename__ = "custom_valuations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    value = Column(Text, unique=True, nullable=False)
    label = Column(Text, nullable=False)
    tone = Column(Text, nullable=False, default="neutral")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AnnouncementInsight(Base):
    __tablename__ = "announcement_insights"
    __table_args__ = (
        UniqueConstraint("stock_symbol", "quarter", "financial_year", "announcement_type", "source_pdf_url",
                         name="uq_ann_insight_sym_q_fy_type_pdf"),
        Index("idx_ann_insight_symbol", "stock_symbol"),
        Index("idx_ann_insight_status", "extraction_status"),
        Index("idx_ann_insight_type", "announcement_type"),
        Index("idx_ann_insight_msg_id", "source_message_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_symbol = Column(String, nullable=False)
    company_name = Column(String)
    quarter = Column(String, nullable=False)
    financial_year = Column(String, nullable=False)
    announcement_type = Column(String, nullable=False)
    source_pdf_url = Column(String)
    source_message_id = Column(Integer, ForeignKey("messages.id"))
    exchange = Column(String, default="BSE")

    # Financial metrics
    revenue = Column(Float)
    revenue_unit = Column(String)
    ebitda = Column(Float)
    ebitda_margin_pct = Column(Float)
    pat = Column(Float)
    pat_margin_pct = Column(Float)
    eps_basic = Column(Float)
    eps_diluted = Column(Float)
    roce_pct = Column(Float)
    roe_pct = Column(Float)
    debt_to_equity = Column(Float)
    working_capital_days = Column(Float)
    free_cash_flow = Column(Float)
    order_book_value = Column(Float)
    dividend_per_share = Column(Float)
    dividend_payout_ratio = Column(Float)
    capex_current_year = Column(Float)
    capex_planned_next = Column(Float)
    revenue_guidance_low = Column(Float)
    revenue_guidance_high = Column(Float)
    export_share_pct = Column(Float)
    domestic_share_pct = Column(Float)
    yoy_revenue_growth_pct = Column(Float)
    qoq_revenue_growth_pct = Column(Float)
    capacity_utilization_pct = Column(Float)

    # Segment / business breakdown (JSON text)
    segment_revenue = Column(Text)
    geography_split = Column(Text)
    product_mix = Column(Text)
    customer_concentration = Column(Text)

    # Forward-looking
    revenue_growth_guidance = Column(Text)
    margin_signal = Column(String)
    industry_tailwinds = Column(Text)
    industry_headwinds = Column(Text)
    management_priorities = Column(Text)
    capex_timeline = Column(Text)
    new_market_entries = Column(Text)
    hiring_plans = Column(Text)

    # Qualitative
    management_outlook = Column(String)
    management_confidence = Column(Integer)
    competitive_moat = Column(Text)
    esg_highlights = Column(Text)
    key_risks = Column(Text)
    growth_drivers = Column(Text)
    next_quarter_outlook = Column(String)

    # AI summaries
    executive_summary = Column(Text)
    investment_thesis = Column(Text)
    key_takeaways = Column(Text)
    next_quarter_prediction = Column(Text)
    bull_case = Column(Text)
    bear_case = Column(Text)

    # Metadata
    raw_ai_response = Column(Text)
    extraction_mode = Column(String)
    pages_processed = Column(Integer)
    extraction_status = Column(String, default="pending")
    extraction_error = Column(Text)
    announcement_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConcallInsight(Base):
    __tablename__ = "concall_insights"
    __table_args__ = (
        UniqueConstraint("stock_symbol", "quarter", "financial_year", "source_pdf_url",
                         name="uq_concall_symbol_q_fy_pdf"),
        Index("idx_concall_symbol", "stock_symbol"),
        Index("idx_concall_status", "extraction_status"),
        Index("idx_concall_quarter_fy", "quarter", "financial_year"),
        Index("idx_concall_msg_id", "source_message_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_symbol = Column(String, nullable=False)
    company_name = Column(String)
    quarter = Column(String, nullable=False)
    financial_year = Column(String, nullable=False)
    source_pdf_url = Column(String)
    source_message_id = Column(Integer, ForeignKey("messages.id"))
    exchange = Column(String, default="BSE")

    # Quantitative metrics
    revenue_mentioned = Column(Float)
    revenue_unit = Column(String)
    ebitda_margin_pct = Column(Float)
    pat_margin_pct = Column(Float)
    capacity_utilization_pct = Column(Float)
    capex_current_year = Column(Float)
    capex_planned_next = Column(Float)
    revenue_guidance_low = Column(Float)
    revenue_guidance_high = Column(Float)
    export_share_pct = Column(Float)
    market_share_pct = Column(Float)
    technical_fee_pct = Column(Float)
    industry_volume = Column(Float)
    yoy_revenue_growth_pct = Column(Float)
    qoq_revenue_growth_pct = Column(Float)

    # Qualitative signals (JSON arrays stored as text)
    management_outlook = Column(String)
    next_quarter_outlook = Column(String)
    management_confidence = Column(Integer)
    growth_drivers = Column(Text)
    key_risks = Column(Text)
    new_products = Column(Text)
    expansion_plans = Column(Text)
    margin_levers = Column(Text)
    competitive_position = Column(Text)
    customer_updates = Column(Text)
    sector_trends = Column(Text)

    # AI-generated summaries
    executive_summary = Column(Text)
    investment_thesis = Column(Text)
    key_takeaways = Column(Text)

    # Metadata
    raw_ai_response = Column(Text)
    transcript_length = Column(Integer)
    extraction_status = Column(String, default="pending")
    extraction_error = Column(Text)
    announcement_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BSEAnnouncementLog(Base):
    __tablename__ = "bse_announcements_log"
    __table_args__ = (
        UniqueConstraint("scrip_code", "announcement_type", "pdf_url",
                         name="uq_bse_scrip_type_pdf"),
        Index("idx_bse_log_scrip_date", "scrip_code", "announcement_date"),
        Index("idx_bse_log_processed", "processed"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scrip_code = Column(String, nullable=False)
    company_name = Column(String)
    announcement_type = Column(String, nullable=False)
    announcement_date = Column(String, nullable=False)
    subject = Column(Text)
    pdf_url = Column(String)
    xml_url = Column(String)
    exchange = Column(String, default="BSE")
    processed = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
