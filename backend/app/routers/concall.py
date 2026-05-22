"""
Concall insights API router.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..database import get_db
from ..cache import cache_get, cache_set

router = APIRouter(prefix="/api/concall", tags=["concall"])


@router.get("/insights")
async def get_concall_insights(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    symbol: Optional[str] = None,
    quarter: Optional[str] = None,
    financial_year: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of concall insights with filters."""
    cache_key = f"concall:list:{page}:{per_page}:{symbol}:{quarter}:{financial_year}:{status}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    offset = (page - 1) * per_page
    where = "WHERE 1=1"
    params: dict = {"limit": per_page, "offset": offset}

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

    count_row = await db.execute(text(f"SELECT COUNT(*) FROM concall_insights {where}"), params)
    total = count_row.scalar()

    rows = await db.execute(text(f"""
        SELECT id, stock_symbol, company_name, quarter, financial_year,
               source_pdf_url, exchange, announcement_date,
               revenue_mentioned, revenue_unit, ebitda_margin_pct, pat_margin_pct,
               capacity_utilization_pct, capex_current_year, capex_planned_next,
               revenue_guidance_low, revenue_guidance_high,
               yoy_revenue_growth_pct, qoq_revenue_growth_pct,
               management_outlook, next_quarter_outlook, management_confidence,
               executive_summary, investment_thesis, key_takeaways,
               growth_drivers, key_risks, new_products,
               expansion_plans, margin_levers, competitive_position,
               customer_updates, sector_trends,
               export_share_pct, market_share_pct, technical_fee_pct,
               extraction_status, created_at
        FROM concall_insights {where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)

    insights = []
    for r in rows.fetchall():
        row = dict(r._mapping)
        # Parse JSON array fields
        import json
        for field in ("key_takeaways", "growth_drivers", "key_risks",
                      "new_products", "margin_levers"):
            if row.get(field):
                try:
                    row[field] = json.loads(row[field])
                except (json.JSONDecodeError, TypeError):
                    pass
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


@router.get("/insights/{insight_id}")
async def get_concall_insight_detail(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get full detail for a single concall insight."""
    row = await db.execute(text("""
        SELECT * FROM concall_insights WHERE id = :id
    """), {"id": insight_id})
    result = row.first()

    if not result:
        raise HTTPException(status_code=404, detail="Insight not found")

    import json
    data = dict(result._mapping)
    for field in ("key_takeaways", "growth_drivers", "key_risks",
                  "new_products", "margin_levers"):
        if data.get(field):
            try:
                data[field] = json.loads(data[field])
            except (json.JSONDecodeError, TypeError):
                pass

    # Parse raw_ai_response for full detail
    if data.get("raw_ai_response"):
        try:
            data["raw_ai_response"] = json.loads(data["raw_ai_response"])
        except (json.JSONDecodeError, TypeError):
            pass

    return data


@router.get("/insights/by-message/{message_id}")
async def get_insight_by_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Lookup concall insight by source message ID."""
    row = await db.execute(text("""
        SELECT id, stock_symbol, company_name, quarter, financial_year,
               management_outlook, next_quarter_outlook, management_confidence,
               executive_summary, investment_thesis, key_takeaways,
               growth_drivers, key_risks, new_products,
               ebitda_margin_pct, capacity_utilization_pct,
               revenue_guidance_low, revenue_guidance_high,
               extraction_status
        FROM concall_insights
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

    import json
    data = dict(result._mapping)
    data["found"] = True
    for field in ("key_takeaways", "growth_drivers", "key_risks", "new_products"):
        if data.get(field):
            try:
                data[field] = json.loads(data[field])
            except (json.JSONDecodeError, TypeError):
                pass

    return data


class ConcallExtractRequest(BaseModel):
    symbol: str
    pdf_url: str
    exchange: str = "BSE"
    company_name: str = ""
    message_id: Optional[int] = None


@router.post("/extract")
async def trigger_concall_extraction(
    body: ConcallExtractRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger concall extraction for a specific PDF."""
    sym = body.symbol.upper()

    # Insert a pending placeholder so status is visible immediately
    # Always reset to pending on re-trigger (allows re-dispatch of lost tasks)
    await db.execute(text("""
        INSERT INTO concall_insights
            (stock_symbol, company_name, quarter, financial_year,
             source_pdf_url, source_message_id, exchange,
             extraction_status, created_at, updated_at)
        VALUES (:sym, :cn, 'TBD', 'TBD', :pdf, :msg_id, :ex,
                'pending', NOW(), NOW())
        ON CONFLICT (stock_symbol, quarter, financial_year, source_pdf_url)
        DO UPDATE SET extraction_status = 'pending',
            updated_at = NOW()
    """), {
        "sym": sym, "cn": body.company_name or "",
        "pdf": body.pdf_url, "msg_id": body.message_id, "ex": body.exchange,
    })
    await db.commit()

    from worker.tasks.concall import run_concall_extraction
    run_concall_extraction.delay(
        stock_symbol=sym,
        pdf_url=body.pdf_url,
        exchange=body.exchange,
        company_name=body.company_name,
        message_id=body.message_id,
    )

    return {
        "success": True,
        "message": f"Concall extraction queued for {sym}",
    }
