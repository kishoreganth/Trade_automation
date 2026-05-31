"""
Messages API router.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..database import get_db
from ..cache import cached, cache_get, cache_set
from ..cache_keys import invalidate_messages, notify_new_message

router = APIRouter(prefix="/api", tags=["messages"])


@router.get("/messages")
async def get_messages(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    option: str = Query("all"),
    exchange: Optional[str] = None,
    sector: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Paginated message list with option/exchange/sector/search filters."""
    cache_key = f"messages:list:{option}:{page}:{per_page}:{exchange}:{sector}:{search}"
    cached_result = await cache_get(cache_key)
    if cached_result:
        return cached_result

    offset = (page - 1) * per_page
    where = "WHERE 1=1"
    params: dict = {"limit": per_page, "offset": offset}

    if option != "all":
        where += " AND m.option = :option"
        params["option"] = option

    if exchange:
        where += " AND m.exchange = :exchange"
        params["exchange"] = exchange

    if sector:
        where += " AND (m.sector = :sector OR COALESCE(s1.sector, s2.sector) = :sector)"
        params["sector"] = sector

    if search:
        where += " AND (m.symbol ILIKE :search OR m.company_name ILIKE :search OR m.sector ILIKE :search)"
        params["search"] = f"%{search}%"

    # Two separate LEFT JOINs instead of OR — lets Postgres use indexes on both.
    # s1 matches NSE symbols, s2 matches BSE scrip codes (numeric symbols).
    join_clause = """
        FROM messages m
        LEFT JOIN stocks s1 ON s1.symbol = m.symbol
        LEFT JOIN stocks s2 ON m.symbol ~ '^\\d+$' AND s2.bse_scrip_code = m.symbol
    """

    count_row = await db.execute(text(f"""
        SELECT COUNT(*) {join_clause} {where}
    """), params)
    total = count_row.scalar()

    rows = await db.execute(text(f"""
        SELECT m.id, m.chat_id, m.message, m.timestamp, m.symbol, m.company_name,
               m.description, m.file_url, m.option,
               COALESCE(s1.sector, s2.sector, m.sector) AS sector,
               m.exchange,
               CASE
                 WHEN m.exchange = 'BSE' THEN
                   CASE
                     WHEN COALESCE(s1.bse_series, s2.bse_series) IN ('M', 'MT') THEN 'BSE_SME'
                     WHEN COALESCE(s1.bse_series, s2.bse_series) IS NOT NULL
                          AND COALESCE(s1.bse_series, s2.bse_series) != '' THEN 'BSE_EQ'
                     WHEN COALESCE(s1.nse_series, s2.nse_series) IN ('SM', 'ST') THEN 'BSE_SME'
                     WHEN COALESCE(s1.nse_series, s2.nse_series) IN ('EQ', 'BE') THEN 'BSE_EQ'
                     ELSE NULL
                   END
                 ELSE
                   CASE
                     WHEN COALESCE(s1.nse_series, s2.nse_series) IN ('SM', 'ST') THEN 'NSE_SME'
                     WHEN COALESCE(s1.nse_series, s2.nse_series) IS NOT NULL
                          AND COALESCE(s1.nse_series, s2.nse_series) != '' THEN 'NSE_EQ'
                     ELSE COALESCE(s1.market_segment, s2.market_segment)
                   END
               END AS market_segment
        {join_clause}
        {where}
        ORDER BY m.timestamp DESC
        LIMIT :limit OFFSET :offset
    """), params)

    messages = [dict(r._mapping) for r in rows.fetchall()]

    result = {
        "messages": messages,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }

    await cache_set(cache_key, result, ttl=10)
    return result


@router.get("/messages/stats")
async def get_message_stats(db: AsyncSession = Depends(get_db)):
    """Full message stats with today_count, unique_symbols, last_message_time.

    Single round-trip:
      - total / today_count / unique_symbols / last_message_time computed via
        FILTER aggregations in one row.
      - by_option fetched separately (cheap aggregation, has index).
    Cached 60s — header values that don't need to be live-precise.
    """
    cached_result = await cache_get("messages:stats")
    if cached_result:
        return cached_result

    main_row = await db.execute(text("""
        SELECT
          COUNT(*)::bigint                                                  AS total,
          COUNT(*) FILTER (WHERE timestamp >= CURRENT_DATE)::bigint         AS today_count,
          COUNT(DISTINCT symbol) FILTER (
            WHERE symbol IS NOT NULL AND symbol <> ''
          )::bigint                                                         AS unique_symbols,
          MAX(timestamp)                                                    AS last_message_time
        FROM messages
    """))
    main = main_row.first()

    by_option = await db.execute(text(
        "SELECT option, COUNT(*) AS cnt FROM messages GROUP BY option"
    ))
    options = {r.option or "unknown": r.cnt for r in by_option.fetchall()}

    last_message_time = main.last_message_time
    result = {
        "total": int(main.total or 0),
        "today_count": int(main.today_count or 0),
        "unique_symbols": int(main.unique_symbols or 0),
        "last_message_time": last_message_time.isoformat() if last_message_time else None,
        "by_option": options,
    }
    await cache_set("messages:stats", result, ttl=60)
    return result


@router.get("/sectors")
async def get_sectors(db: AsyncSession = Depends(get_db)):
    """Get distinct sectors from messages and stocks."""
    cached_result = await cache_get("sectors:list")
    if cached_result:
        return cached_result

    rows = await db.execute(text(
        "SELECT DISTINCT sector FROM messages WHERE sector IS NOT NULL AND sector != '' "
        "UNION "
        "SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL AND sector != '' "
        "ORDER BY sector"
    ))
    result = {"sectors": [r[0] for r in rows.fetchall()]}
    await cache_set("sectors:list", result, ttl=300)
    return result


@router.post("/trigger_message")
async def trigger_message(body: dict, db: AsyncSession = Depends(get_db)):
    """Save a new message and broadcast via WebSocket."""
    now = datetime.utcnow()
    result = await db.execute(text("""
        INSERT INTO messages (chat_id, message, timestamp, symbol, company_name, description, file_url, option, sector, exchange)
        VALUES (:cid, :msg, :ts, :sym, :cn, :desc, :url, :opt, :sector, :ex)
        RETURNING id
    """), {
        "cid": body.get("chat_id", "manual"),
        "msg": body.get("message", ""),
        "ts": now,
        "sym": body.get("symbol", ""),
        "cn": body.get("company_name", ""),
        "desc": body.get("description", ""),
        "url": body.get("file_url", ""),
        "opt": body.get("option", "all"),
        "sector": body.get("sector", ""),
        "ex": body.get("exchange", "NSE"),
    })
    msg_id = result.scalar()
    await db.commit()

    await invalidate_messages()
    await notify_new_message({
        "id": msg_id,
        "symbol": body.get("symbol", ""),
        "company_name": body.get("company_name", ""),
        "timestamp": now,
    })

    return {"success": True, "id": msg_id}
