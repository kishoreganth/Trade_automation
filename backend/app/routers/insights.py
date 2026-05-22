"""
Announcement insights API router — serves Investor Presentation and Monthly Business Update AI data.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..database import get_db
from ..cache import cache_get, cache_set

router = APIRouter(prefix="/api/insights", tags=["insights"])

_JSON_FIELDS = (
    "segment_revenue", "geography_split", "product_mix",
    "industry_tailwinds", "industry_headwinds",
    "management_priorities", "new_market_entries",
    "key_risks", "growth_drivers", "key_takeaways",
)


def _parse_json_fields(data: dict) -> dict:
    for field in _JSON_FIELDS:
        if data.get(field):
            try:
                data[field] = json.loads(data[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return data


@router.get("/announcements")
async def get_announcement_insights(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    announcement_type: Optional[str] = None,
    symbol: Optional[str] = None,
    quarter: Optional[str] = None,
    financial_year: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of announcement insights with filters."""
    cache_key = f"ann_insights:list:{page}:{per_page}:{announcement_type}:{symbol}:{quarter}:{financial_year}:{status}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    offset = (page - 1) * per_page
    where = "WHERE 1=1"
    params: dict = {"limit": per_page, "offset": offset}

    if announcement_type:
        where += " AND announcement_type = :ann_type"
        params["ann_type"] = announcement_type

    if symbol:
        where += " AND stock_symbol = :symbol"
        params["symbol"] = symbol.upper()

    if quarter:
        where += " AND quarter = :quarter"
        params["quarter"] = quarter

    if financial_year:
        where += " AND financial_year = :fy"
        params["fy"] = financial_year

    if status:
        where += " AND extraction_status = :status"
        params["status"] = status
    else:
        where += " AND extraction_status = 'completed'"

    count_row = await db.execute(text(f"SELECT COUNT(*) FROM announcement_insights {where}"), params)
    total = count_row.scalar()

    rows = await db.execute(text(f"""
        SELECT id, stock_symbol, company_name, quarter, financial_year,
               announcement_type, source_pdf_url, exchange, announcement_date,
               revenue, revenue_unit, ebitda, ebitda_margin_pct, pat, pat_margin_pct,
               eps_basic, eps_diluted, roce_pct, roe_pct, debt_to_equity,
               working_capital_days, free_cash_flow, order_book_value,
               dividend_per_share, capex_current_year, capex_planned_next,
               revenue_guidance_low, revenue_guidance_high,
               export_share_pct, domestic_share_pct,
               yoy_revenue_growth_pct, qoq_revenue_growth_pct, capacity_utilization_pct,
               segment_revenue, geography_split, product_mix,
               margin_signal, management_outlook, management_confidence,
               next_quarter_outlook,
               executive_summary, investment_thesis, key_takeaways,
               bull_case, bear_case, next_quarter_prediction,
               growth_drivers, key_risks, management_priorities,
               extraction_status, extraction_mode, pages_processed, created_at
        FROM announcement_insights {where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)

    insights = []
    for r in rows.fetchall():
        row = dict(r._mapping)
        _parse_json_fields(row)
        insights.append(row)

    result = {
        "insights": insights,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }

    await cache_set(cache_key, result, ttl=30)
    return result


@router.get("/announcements/{insight_id}")
async def get_announcement_insight_detail(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get full detail for a single announcement insight."""
    row = await db.execute(text("SELECT * FROM announcement_insights WHERE id = :id"), {"id": insight_id})
    result = row.first()

    if not result:
        raise HTTPException(status_code=404, detail="Insight not found")

    data = dict(result._mapping)
    _parse_json_fields(data)

    if data.get("raw_ai_response"):
        try:
            data["raw_ai_response"] = json.loads(data["raw_ai_response"])
        except (json.JSONDecodeError, TypeError):
            pass

    return data


@router.get("/announcements/by-message/{message_id}")
async def get_announcement_insight_by_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Lookup announcement insight by source message ID."""
    row = await db.execute(text("""
        SELECT id, stock_symbol, company_name, quarter, financial_year,
               announcement_type, extraction_status, extraction_mode,
               revenue, revenue_unit, ebitda, ebitda_margin_pct, pat, pat_margin_pct,
               eps_basic, eps_diluted, roce_pct, roe_pct, debt_to_equity,
               free_cash_flow, order_book_value,
               revenue_guidance_low, revenue_guidance_high,
               yoy_revenue_growth_pct, qoq_revenue_growth_pct,
               segment_revenue, geography_split,
               margin_signal, management_outlook, management_confidence,
               next_quarter_outlook,
               executive_summary, investment_thesis, key_takeaways,
               bull_case, bear_case, next_quarter_prediction,
               growth_drivers, key_risks, management_priorities
        FROM announcement_insights
        WHERE source_message_id = :msg_id
        ORDER BY CASE extraction_status
            WHEN 'completed' THEN 0 WHEN 'processing' THEN 1
            WHEN 'pending' THEN 2 ELSE 3 END,
            updated_at DESC
        LIMIT 1
    """), {"msg_id": message_id})
    result = row.first()

    if not result:
        return {"found": False}

    data = dict(result._mapping)
    data["found"] = True
    _parse_json_fields(data)

    return data


class AnnouncementExtractRequest(BaseModel):
    symbol: str
    pdf_url: str
    announcement_type: str
    exchange: str = "BSE"
    company_name: str = ""
    message_id: Optional[int] = None


@router.post("/extract")
async def trigger_announcement_extraction(
    body: AnnouncementExtractRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger announcement insight extraction for a specific PDF."""
    valid_types = ("investor_presentation", "monthly_business_update")
    if body.announcement_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"announcement_type must be one of: {valid_types}",
        )

    sym = body.symbol.upper()

    # Insert a pending placeholder so status is visible immediately
    # Always reset to pending on re-trigger (allows re-dispatch of lost tasks)
    await db.execute(text("""
        INSERT INTO announcement_insights
            (stock_symbol, company_name, quarter, financial_year,
             announcement_type, source_pdf_url, source_message_id, exchange,
             extraction_status, created_at, updated_at)
        VALUES (:sym, :cn, 'TBD', 'TBD', :ann_type, :pdf, :msg_id, :ex,
                'pending', NOW(), NOW())
        ON CONFLICT (stock_symbol, quarter, financial_year, announcement_type, source_pdf_url)
        DO UPDATE SET extraction_status = 'pending',
            updated_at = NOW()
    """), {
        "sym": sym, "cn": body.company_name or "",
        "ann_type": body.announcement_type,
        "pdf": body.pdf_url, "msg_id": body.message_id, "ex": body.exchange,
    })
    await db.commit()

    from worker.tasks.announcement_insight import run_announcement_extraction
    run_announcement_extraction.delay(
        stock_symbol=sym,
        pdf_url=body.pdf_url,
        announcement_type=body.announcement_type,
        exchange=body.exchange,
        company_name=body.company_name,
        message_id=body.message_id,
    )

    return {
        "success": True,
        "message": f"Announcement extraction queued for {sym} ({body.announcement_type})",
    }


@router.get("/all")
async def get_all_insights(
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    insight_type: Optional[str] = None,
    symbol: Optional[str] = None,
    quarter: Optional[str] = None,
    financial_year: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Unified paginated list of ALL AI insights (concall + announcements)."""
    offset = (page - 1) * per_page

    # Build WHERE clauses for both tables
    concall_where = "WHERE 1=1"
    ann_where = "WHERE 1=1"
    params: dict = {"limit": per_page, "offset": offset}

    if insight_type:
        if insight_type == "concall":
            ann_where += " AND 1=0"
        elif insight_type in ("investor_presentation", "monthly_business_update"):
            concall_where += " AND 1=0"
            ann_where += " AND announcement_type = :ann_type"
            params["ann_type"] = insight_type

    if symbol:
        concall_where += " AND stock_symbol = :symbol"
        ann_where += " AND stock_symbol = :symbol"
        params["symbol"] = symbol.upper()

    if quarter:
        concall_where += " AND quarter = :quarter"
        ann_where += " AND quarter = :quarter"
        params["quarter"] = quarter

    if financial_year:
        concall_where += " AND financial_year = :fy"
        ann_where += " AND financial_year = :fy"
        params["fy"] = financial_year

    if status:
        concall_where += " AND extraction_status = :status"
        ann_where += " AND extraction_status = :status"
        params["status"] = status

    # Count
    count_sql = f"""
        SELECT (
            SELECT COUNT(*) FROM concall_insights {concall_where}
        ) + (
            SELECT COUNT(*) FROM announcement_insights {ann_where}
        ) AS total
    """
    count_row = await db.execute(text(count_sql), params)
    total = count_row.scalar() or 0

    # UNION query
    sql = f"""
        SELECT id, 'concall' AS insight_type, stock_symbol, company_name,
               quarter, financial_year, source_pdf_url, source_message_id,
               exchange, extraction_status,
               management_outlook, executive_summary, investment_thesis,
               created_at, updated_at
        FROM concall_insights {concall_where}

        UNION ALL

        SELECT id, announcement_type AS insight_type, stock_symbol, company_name,
               quarter, financial_year, source_pdf_url, source_message_id,
               exchange, extraction_status,
               management_outlook, executive_summary, investment_thesis,
               created_at, updated_at
        FROM announcement_insights {ann_where}

        ORDER BY updated_at DESC
        LIMIT :limit OFFSET :offset
    """

    rows = await db.execute(text(sql), params)
    insights = [dict(r._mapping) for r in rows.fetchall()]

    return {
        "insights": insights,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 1,
    }
