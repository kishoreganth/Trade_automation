"""
PE Analysis API router.
Extracted from: nse_url_test.py (/api/pe_analysis, /api/pe_analysis/filters, 
    /api/pe_analysis/report_summary, DELETE/PUT endpoints)
"""

import re
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

from ..database import get_db
from ..cache import cached, cache_get, cache_set
from ..cache_keys import invalidate_pe_analysis
from ..constants import (
    VALUATION_OPTIONS, VALUATION_VALUES, canonicalize_valuation, valuation_tone,
    VALUATION_TONE_BULLISH, VALUATION_TONE_BEARISH,
)
from worker.tasks.extraction import run_quarterly_extraction
from ..services.audit_log import log_pe_action

router = APIRouter(prefix="/api", tags=["pe_analysis"])

# Feature flag: set to True to enable cross-exchange deduplication.
# When False, ALL rows are shown (no hiding behind ROW_NUMBER).
DEDUP_ENABLED = True


def _quarter_index(q: str) -> int:
    return {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}.get(q, 0)


def _fy_to_year(fy: str) -> int:
    """Normalize any financial_year format to ending calendar year number.
    '2026'->2026, 'FY26'->2026, 'FY2025-26'->2026, '2025-26'->2026."""
    if not fy:
        return 0
    fy = fy.strip()
    if fy.isdigit():
        y = int(fy)
        return y if y > 100 else 2000 + y
    m = re.match(r"FY(\d{2})$", fy)
    if m:
        return 2000 + int(m.group(1))
    m = re.match(r"FY(\d{4})-(\d{2})$", fy)
    if m:
        return 2000 + int(m.group(2))
    m = re.match(r"(\d{4})-(\d{2})$", fy)
    if m:
        return 2000 + int(m.group(2))
    m = re.match(r"FY(\d{4})$", fy)
    if m:
        return int(m.group(1))
    return 0


def _resolved_symbol_sql(qr: str = "qr", s1: str = "s1", s2: str = "s2") -> str:
    """Canonical NSE symbol for a quarterly_results row.

    Numeric stock_symbol values are BSE scrip codes and must resolve via
    bse_token (s2). Using COALESCE(s1, s2) first would match a stocks row whose
    symbol is the scrip code (e.g. 524091) instead of the NSE ticker (CARYSIL).
    """
    return f"""CASE
      WHEN {qr}.stock_symbol ~ '^\\d+$'
        THEN COALESCE({s2}.symbol, {qr}.stock_symbol)
      ELSE COALESCE({s1}.symbol, {qr}.stock_symbol)
    END"""


def _resolved_stock_field_sql(field: str, qr: str = "qr", s1: str = "s1", s2: str = "s2") -> str:
    """Resolve a stocks column using the same numeric-vs-NSE join priority."""
    return f"""CASE
      WHEN {qr}.stock_symbol ~ '^\\d+$'
        THEN COALESCE({s2}.{field}, {s1}.{field})
      ELSE COALESCE({s1}.{field}, {s2}.{field})
    END"""


def _resolved_market_segment_sql(qr: str = "qr", s1: str = "s1", s2: str = "s2") -> str:
    """Derive market_segment consistent with the quarterly result's exchange."""
    return f"""CASE
      WHEN {qr}.exchange = 'BSE' THEN
        CASE
          WHEN COALESCE({s1}.bse_series, {s2}.bse_series) IN ('M', 'MT') THEN 'BSE_SME'
          WHEN COALESCE({s1}.bse_series, {s2}.bse_series) IS NOT NULL
               AND COALESCE({s1}.bse_series, {s2}.bse_series) != '' THEN 'BSE_EQ'
          WHEN COALESCE({s1}.nse_series, {s2}.nse_series) IN ('SM', 'ST') THEN 'BSE_SME'
          WHEN COALESCE({s1}.nse_series, {s2}.nse_series) IN ('EQ', 'BE') THEN 'BSE_EQ'
          ELSE NULL
        END
      ELSE
        CASE
          WHEN COALESCE({s1}.nse_series, {s2}.nse_series) IN ('SM', 'ST') THEN 'NSE_SME'
          WHEN COALESCE({s1}.nse_series, {s2}.nse_series) IS NOT NULL
               AND COALESCE({s1}.nse_series, {s2}.nse_series) != '' THEN 'NSE_EQ'
          ELSE {_resolved_stock_field_sql("market_segment", qr, s1, s2)}
        END
    END"""


def _dedup_history(history: list[dict]) -> list[dict]:
    """Keep only the latest row per (quarter, normalized_fy) combo."""
    seen: dict[tuple, dict] = {}
    for h in history:
        key = (h.get("quarter"), _fy_to_year(h.get("financial_year", "")))
        existing = seen.get(key)
        if existing is None or h.get("id", 0) > existing.get("id", 0):
            seen[key] = h
    return list(seen.values())


def _compute_derived_fields(row: dict, history: list[dict]) -> dict:
    """Compute EPS Q/Q, Y/Y, Cum EPS, Cum Prev FY, Prev FY EPS, FY EPS Est with labels."""
    qtr = row.get("quarter", "")
    fy = row.get("financial_year", "")
    qi = _quarter_index(qtr)
    fy_year = _fy_to_year(fy)

    deduped = _dedup_history(history)

    same_fy = [h for h in deduped if _fy_to_year(h.get("financial_year", "")) == fy_year]
    same_fy_sorted = sorted(same_fy, key=lambda x: _quarter_index(x.get("quarter", "")))

    prev_fy_year = fy_year - 1 if fy_year > 0 else 0
    prev_fy_rows = [h for h in deduped if _fy_to_year(h.get("financial_year", "")) == prev_fy_year]
    prev_fy_sorted = sorted(prev_fy_rows, key=lambda x: _quarter_index(x.get("quarter", "")))

    # EPS Q/Q: raw EPS value of previous quarter in same FY
    eps_qoq = None
    eps_qoq_label = ""
    if qi > 1:
        prev_q = f"Q{qi - 1}"
        prev_row = next((h for h in same_fy if h.get("quarter") == prev_q), None)
        if prev_row and prev_row.get("qtr_eps") is not None:
            eps_qoq = round(prev_row["qtr_eps"], 2)
            eps_qoq_label = prev_q

    # EPS Y/Y: raw EPS value of same quarter in prev FY
    eps_yoy = None
    eps_yoy_label = ""
    if prev_fy_year > 0:
        same_q_prev = next((h for h in prev_fy_rows if h.get("quarter") == qtr), None)
        if same_q_prev and same_q_prev.get("qtr_eps") is not None:
            eps_yoy = round(same_q_prev["qtr_eps"], 2)
            eps_yoy_label = f"Prev {qtr}"

    # Cumulative EPS: for Q1-Q3 use stored cum_eps; for Q4 use FY row or sum Q1-Q4
    cum_eps = None
    cum_eps_label = ""
    if qi > 0 and qi < 4:
        stored_cum = row.get("cum_eps_stored")
        if stored_cum is not None:
            cum_eps = round(stored_cum, 2)
        else:
            cur_q_hist = next((h for h in same_fy if h.get("quarter") == qtr), None)
            if cur_q_hist and cur_q_hist.get("cum_eps") is not None:
                cum_eps = round(cur_q_hist["cum_eps"], 2)
            else:
                vals = [h.get("qtr_eps") for h in same_fy_sorted
                        if _quarter_index(h.get("quarter", "")) <= qi and h.get("qtr_eps") is not None]
                if vals:
                    cum_eps = round(sum(vals), 2)
        cum_eps_label = f"N{qi * 3}"
    elif qi == 4:
        fy_row = next((h for h in same_fy if h.get("quarter") == "FY"), None)
        if fy_row and fy_row.get("qtr_eps") is not None:
            cum_eps = round(fy_row["qtr_eps"], 2)
        else:
            vals = [h.get("qtr_eps") for h in same_fy_sorted
                    if h.get("quarter") in ("Q1", "Q2", "Q3", "Q4") and h.get("qtr_eps") is not None]
            if len(vals) == 4:
                cum_eps = round(sum(vals), 2)
        cum_eps_label = "N12"

    # Cumulative Prev FY: for Q1-Q3 use stored cum_eps from prev FY history; for Q4 use FY row or sum
    cum_prev_fy = None
    cum_prev_fy_label = ""
    if qi > 0 and prev_fy_rows:
        if qi < 4:
            prev_q_match = next((h for h in prev_fy_rows if h.get("quarter") == qtr), None)
            if prev_q_match and prev_q_match.get("cum_eps") is not None:
                cum_prev_fy = round(prev_q_match["cum_eps"], 2)
            else:
                vals = [h.get("qtr_eps") for h in prev_fy_sorted
                        if _quarter_index(h.get("quarter", "")) <= qi and h.get("qtr_eps") is not None]
                if vals:
                    cum_prev_fy = round(sum(vals), 2)
            cum_prev_fy_label = f"Prev N{qi * 3}"
        else:
            fy_row_prev = next((h for h in prev_fy_rows if h.get("quarter") == "FY"), None)
            if fy_row_prev and fy_row_prev.get("qtr_eps") is not None:
                cum_prev_fy = round(fy_row_prev["qtr_eps"], 2)
            else:
                vals = [h.get("qtr_eps") for h in prev_fy_sorted
                        if h.get("quarter") in ("Q1", "Q2", "Q3", "Q4") and h.get("qtr_eps") is not None]
                if len(vals) == 4:
                    cum_prev_fy = round(sum(vals), 2)
            cum_prev_fy_label = "Prev N12"

    # Prev FY EPS: full year sum of previous FY
    prev_fy_eps = None
    prev_fy_eps_label = "Prev FY"
    if prev_fy_sorted:
        # Check if there's an FY row with stored cum_eps
        fy_row = next((h for h in prev_fy_rows if h.get("quarter") == "FY"), None)
        if fy_row and fy_row.get("qtr_eps") is not None:
            prev_fy_eps = round(fy_row["qtr_eps"], 2)
        else:
            vals = [h.get("qtr_eps") for h in prev_fy_sorted
                    if h.get("quarter") in ("Q1", "Q2", "Q3", "Q4") and h.get("qtr_eps") is not None]
            if len(vals) == 4:
                prev_fy_eps = round(sum(vals), 2)

    # FY EPS Estimated: use stored fy_eps_stored if available, else compute using formula
    fy_eps_est = None
    has_consolidated = row.get("fy_from_consolidated", False) or row.get("eps_diluted_consolidated") is not None or row.get("eps_basic_consolidated") is not None
    fy_eps_est_label = "FY (C)" if has_consolidated else "FY (S)"
    stored_fy = row.get("fy_eps_stored")
    if stored_fy is not None:
        fy_eps_est = round(stored_fy, 2)
    elif qi > 0:
        # Compute using best available cumulative: prefer N9*4/3, then N6*2, then N3*4, then N12
        n9_row = next((h for h in same_fy if h.get("quarter") == "Q3"), None)
        n6_row = next((h for h in same_fy if h.get("quarter") == "Q2"), None)
        n3_row = next((h for h in same_fy if h.get("quarter") == "Q1"), None)

        if qi >= 3 and n9_row and n9_row.get("cum_eps") is not None:
            fy_eps_est = round(n9_row["cum_eps"] * 4 / 3, 2)
        elif qi >= 2 and n6_row and n6_row.get("cum_eps") is not None:
            fy_eps_est = round(n6_row["cum_eps"] * 2, 2)
        elif n3_row and n3_row.get("cum_eps") is not None:
            fy_eps_est = round(n3_row["cum_eps"] * 4, 2)
        elif cum_eps is not None:
            if qi == 1:
                fy_eps_est = round(cum_eps * 4, 2)
            elif qi == 2:
                fy_eps_est = round(cum_eps * 2, 2)
            elif qi == 3:
                fy_eps_est = round(cum_eps * 4 / 3, 2)
            elif qi == 4:
                fy_eps_est = cum_eps

    row["eps_qoq"] = eps_qoq
    row["eps_qoq_label"] = eps_qoq_label
    row["eps_yoy"] = eps_yoy
    row["eps_yoy_label"] = eps_yoy_label
    row["cum_eps"] = cum_eps
    row["cum_eps_label"] = cum_eps_label
    row["cum_prev_fy"] = cum_prev_fy
    row["cum_prev_fy_label"] = cum_prev_fy_label
    row["prev_fy_eps"] = prev_fy_eps
    row["prev_fy_eps_label"] = prev_fy_eps_label
    row["fy_eps_estimated"] = fy_eps_est
    row["fy_eps_est_label"] = fy_eps_est_label
    return row


@router.get("/pe_analysis")
async def get_pe_analysis(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=5000),
    valuation_filter: str = Query("pending"),
    year: Optional[str] = None,
    quarter: Optional[str] = None,
    exchange: Optional[str] = None,
    sector: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    valuation: Optional[str] = None,
    signal: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Paginated PE analysis results with computed fields."""
    cache_key = f"pe:list:{valuation_filter}:{page}:{per_page}:{year}:{quarter}:{exchange}:{sector}:{search}:{date_from}:{date_to}:{valuation}:{signal}"
    cached_result = await cache_get(cache_key)
    if cached_result:
        return cached_result

    offset = (page - 1) * per_page
    params = {"limit": per_page, "offset": offset}

    scope_conditions: list[str] = []
    outer_conditions: list[str] = []

    # All filters go INSIDE the CTE (preserves old per-page dedup).
    # For PENDING: also exclude rows whose stock+quarter+FY already has
    # a reviewed counterpart — this prevents the same stock from showing
    # on both PE Pending and PE Reviewed simultaneously.
    if valuation_filter == "pending":
        scope_conditions.append("(qr.valuation IS NULL OR qr.valuation = '')")
        if DEDUP_ENABLED:
            # Hide rows whose resolved_symbol+quarter+FY already has a reviewed row
            scope_conditions.append(f"""
                NOT EXISTS (
                    SELECT 1 FROM quarterly_results r
                    LEFT JOIN stocks rs1 ON rs1.symbol = r.stock_symbol
                    LEFT JOIN stocks rs2 ON rs2.bse_token = CASE
                        WHEN r.stock_symbol ~ '^\\d+$' THEN CAST(r.stock_symbol AS INT)
                    END
                    WHERE {_resolved_symbol_sql("r", "rs1", "rs2")}
                        = {_resolved_symbol_sql("qr", "s1", "s2")}
                      AND r.quarter = qr.quarter
                      AND RIGHT(r.financial_year, 2) = RIGHT(qr.financial_year, 2)
                      AND r.valuation IS NOT NULL AND r.valuation != ''
                      AND (r.extraction_status = 'completed' OR r.user_reviewed = TRUE)
                )
            """)
            # Hide FY rows when a Q4 row exists for the same stock+year
            scope_conditions.append(f"""
                NOT (qr.quarter = 'FY' AND EXISTS (
                    SELECT 1 FROM quarterly_results q4
                    WHERE q4.stock_symbol = qr.stock_symbol
                      AND q4.quarter = 'Q4'
                      AND RIGHT(q4.financial_year, 2) = RIGHT(qr.financial_year, 2)
                ))
            """)
    elif valuation_filter == "reviewed":
        scope_conditions.append("qr.valuation IS NOT NULL AND qr.valuation != ''")
        scope_conditions.append("(qr.extraction_status = 'completed' OR qr.user_reviewed = TRUE)")
    elif valuation_filter == "failed":
        scope_conditions.append("qr.extraction_status IN ('failed', 'error')")
    if year:
        year_num = _fy_to_year(year)
        if year_num:
            yr_short = str(year_num % 100).zfill(2)
            scope_conditions.append("qr.financial_year LIKE :year_pattern")
            params["year_pattern"] = f"%{yr_short}%"
        else:
            scope_conditions.append("qr.financial_year = :year")
            params["year"] = year
    if quarter:
        scope_conditions.append("qr.quarter = :quarter")
        params["quarter"] = quarter
    if exchange:
        scope_conditions.append("qr.exchange = :exchange")
        params["exchange"] = exchange
    if sector:
        scope_conditions.append("COALESCE(s1.sector, s2.sector) = :sector")
        params["sector"] = sector
    if search:
        scope_conditions.append(
            "(qr.stock_symbol ILIKE :search OR qr.company_name ILIKE :search"
            " OR s1.symbol ILIKE :search"
            " OR CAST(s2.bse_token AS TEXT) LIKE :search_exact)"
        )
        params["search"] = f"%{search}%"
        params["search_exact"] = f"%{search}%"
    if date_from:
        try:
            df_dt = datetime.strptime(date_from[:10], "%Y-%m-%d")
            scope_conditions.append("COALESCE(qr.announcement_date, qr.created_at) >= :date_from")
            params["date_from"] = df_dt
        except ValueError:
            pass
    if date_to:
        try:
            dt_dt = datetime.strptime(date_to[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999000)
            scope_conditions.append("COALESCE(qr.announcement_date, qr.created_at) <= :date_to")
            params["date_to"] = dt_dt
        except ValueError:
            pass
    if valuation:
        scope_conditions.append("qr.valuation = :valuation_exact")
        params["valuation_exact"] = valuation
    if signal:
        scope_conditions.append("qr.recommendation = :signal_exact")
        params["signal_exact"] = signal

    where_inside = "WHERE " + " AND ".join(scope_conditions) if scope_conditions else ""
    outer_filter = " AND ".join(outer_conditions)

    # Window-function dedup: ONE row per (resolved_symbol, quarter, FY).
    # Two LEFT JOINs (each index-friendly) instead of OR-based JOIN which kills perf.
    # s1 = match by symbol (NSE entries), s2 = match by bse_token (BSE numeric entries).
    #
    # PE Reviewed ranking: prefer rows with richest user data (signal, comments,
    # target_price), then BSE exchange for ties. NEVER hides reviewed rows —
    # only picks the best representative when dual-listed duplicates exist.
    # PE Pending ranking: prefer completed extraction, latest announcement.
    if valuation_filter == "reviewed":
        rn_order = f"""
              PARTITION BY {_resolved_symbol_sql()}, qr.quarter, RIGHT(qr.financial_year, 2)
              ORDER BY
                CASE WHEN qr.recommendation IS NOT NULL AND qr.recommendation != '' THEN 0 ELSE 1 END,
                CASE WHEN qr.target_price IS NOT NULL THEN 0 ELSE 1 END,
                CASE WHEN qr.comments IS NOT NULL AND qr.comments != '' THEN 0 ELSE 1 END,
                CASE WHEN qr.exchange = 'BSE' THEN 0 ELSE 1 END,
                qr.announcement_date DESC NULLS LAST,
                qr.id DESC"""
    else:
        rn_order = f"""
              PARTITION BY {_resolved_symbol_sql()}, qr.quarter, RIGHT(qr.financial_year, 2)
              ORDER BY
                CASE WHEN qr.extraction_status = 'completed' OR qr.user_reviewed = TRUE THEN 0 ELSE 1 END,
                qr.announcement_date DESC NULLS LAST,
                qr.id DESC"""

    dedup_cte = f"""
        WITH ranked AS (
          SELECT qr.*,
            COALESCE(qr.eps_diluted_consolidated, qr.eps_basic_consolidated,
                     qr.eps_diluted_standalone, qr.eps_basic_standalone) AS qtr_eps,
            COALESCE(qr.cumulative_eps_diluted_consolidated, qr.cumulative_eps_basic_consolidated,
                     qr.cumulative_eps_diluted_standalone, qr.cumulative_eps_basic_standalone) AS cum_eps_stored,
            COALESCE(
              qr.fy_eps_diluted_consolidated, qr.fy_eps_basic_consolidated,
              qr.fy_eps_diluted_standalone, qr.fy_eps_basic_standalone
            ) AS fy_eps_stored,
            (qr.fy_eps_diluted_consolidated IS NOT NULL
             OR qr.fy_eps_basic_consolidated IS NOT NULL) AS fy_from_consolidated,
            {_resolved_symbol_sql()} AS resolved_symbol,
            {_resolved_stock_field_sql("sector")} AS sector,
            {_resolved_stock_field_sql("sub_sector")} AS sub_sector,
            {_resolved_market_segment_sql()} AS market_segment,
            ROW_NUMBER() OVER ({rn_order}
            ) AS rn
          FROM quarterly_results qr
          LEFT JOIN stocks s1 ON s1.symbol = qr.stock_symbol
          LEFT JOIN stocks s2 ON s2.bse_token = CASE
            WHEN qr.stock_symbol ~ '^\\d+$' THEN CAST(qr.stock_symbol AS INT)
          END
          {where_inside}
        )
    """

    outer_where = f"AND {outer_filter}" if outer_filter else ""

    rn_filter = "rn = 1" if DEDUP_ENABLED else "TRUE"

    count_sql = f"""
        {dedup_cte}
        SELECT COUNT(*) FROM ranked WHERE {rn_filter} {outer_where}
    """
    count_row = await db.execute(text(count_sql), params)
    total = count_row.scalar()

    data_sql = f"""
        {dedup_cte}
        SELECT * FROM ranked WHERE {rn_filter} {outer_where}
        ORDER BY COALESCE(announcement_date, created_at) DESC
        LIMIT :limit OFFSET :offset
    """
    rows = await db.execute(text(data_sql), params)
    results = [dict(r._mapping) for r in rows.fetchall()]

    # Fetch history for all symbols in this page to compute derived fields
    symbols = list({r["stock_symbol"] for r in results if r.get("stock_symbol")})
    history_map: dict[str, list[dict]] = {s: [] for s in symbols}

    if symbols:
        hist_rows = await db.execute(text("""
            SELECT id, stock_symbol, quarter, financial_year,
              COALESCE(eps_diluted_consolidated, eps_basic_consolidated,
                       eps_diluted_standalone, eps_basic_standalone) AS qtr_eps,
              COALESCE(cumulative_eps_diluted_consolidated, cumulative_eps_basic_consolidated,
                       cumulative_eps_diluted_standalone, cumulative_eps_basic_standalone) AS cum_eps
            FROM quarterly_results
            WHERE stock_symbol = ANY(:syms) AND (extraction_status = 'completed' OR user_reviewed = TRUE)
            ORDER BY stock_symbol, financial_year, quarter, id
        """), {"syms": symbols})
        for h in hist_rows.fetchall():
            hd = dict(h._mapping)
            if hd.get("qtr_eps") is not None:
                history_map.setdefault(hd["stock_symbol"], []).append(hd)

    for row in results:
        sym = row.get("stock_symbol", "")
        _compute_derived_fields(row, history_map.get(sym, []))

    response = {
        "results": results,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }

    await cache_set(cache_key, response, ttl=15)
    return response


_VALUATION_VALUE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")


def _normalize_custom_value(raw: str) -> str:
    """Coerce free-form input ('under valued', 'My Tag', 'TEST 1') to a canonical
    UPPER_SNAKE_CASE value that can live alongside the built-in options."""
    s = (raw or "").strip().upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s).strip("_")
    return s


@router.get("/pe_analysis/valuation_options")
async def get_valuation_options(db: AsyncSession = Depends(get_db)):
    """
    Returns the merged valuation list (built-in + user-created custom).
    Each item carries `is_custom` so the UI can show a delete affordance only
    for custom rows. Built-ins are defined in `app.constants.VALUATION_OPTIONS`
    and CANNOT be deleted.
    """
    custom_rows = await db.execute(text(
        "SELECT id, value, label, tone FROM custom_valuations ORDER BY created_at"
    ))
    custom = [
        {"value": r.value, "label": r.label, "tone": r.tone, "is_custom": True, "id": r.id}
        for r in custom_rows.fetchall()
    ]

    builtins = [{**opt, "is_custom": False} for opt in VALUATION_OPTIONS]

    # Drop any custom entries that collide with a built-in value (shouldn't happen
    # because POST blocks it, but defensive).
    builtin_values = {b["value"] for b in builtins}
    custom = [c for c in custom if c["value"] not in builtin_values]

    return {"options": builtins + custom}


@router.post("/pe_analysis/valuation_options")
async def create_custom_valuation(body: dict, db: AsyncSession = Depends(get_db)):
    """
    Create a new custom valuation remark. Auto-normalizes the input string
    (e.g. 'My Tag' -> 'MY_TAG'). Rejects collisions with built-in values
    or existing customs.
    """
    raw = (body.get("value") or body.get("label") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="value or label is required")

    value = _normalize_custom_value(raw)
    if not _VALUATION_VALUE_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail="Value must start with a letter and be 2-50 chars (A-Z, 0-9, _).",
        )
    if value in VALUATION_VALUES:
        raise HTTPException(
            status_code=409,
            detail=f"'{value}' is a built-in remark and cannot be added as custom.",
        )

    label = (body.get("label") or raw).strip()[:60]
    tone = (body.get("tone") or "neutral").strip().lower()
    if tone not in ("bullish", "neutral", "bearish", "ignored"):
        tone = "neutral"

    try:
        result = await db.execute(text("""
            INSERT INTO custom_valuations (value, label, tone)
            VALUES (:v, :l, :t)
            RETURNING id, value, label, tone
        """), {"v": value, "l": label, "t": tone})
        await db.commit()
    except Exception as e:
        await db.rollback()
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"'{value}' already exists.")
        raise

    row = result.first()
    await invalidate_pe_analysis()
    return {
        "value": row.value,
        "label": row.label,
        "tone": row.tone,
        "is_custom": True,
        "id": row.id,
    }


@router.delete("/pe_analysis/valuation_options/{value}")
async def delete_custom_valuation(value: str, db: AsyncSession = Depends(get_db)):
    """
    Delete a custom valuation. Built-in remarks cannot be deleted (returns 403).
    Existing rows in `quarterly_results` that reference the deleted value are
    LEFT INTACT — they continue to display as the (now-orphan) string until
    the user edits them. We don't cascade-update because that would silently
    rewrite user data.
    """
    canon = _normalize_custom_value(value)
    if canon in VALUATION_VALUES:
        raise HTTPException(status_code=403, detail="Built-in remarks cannot be deleted.")

    result = await db.execute(text(
        "DELETE FROM custom_valuations WHERE value = :v RETURNING id"
    ), {"v": canon})
    await db.commit()
    if result.first() is None:
        raise HTTPException(status_code=404, detail=f"Custom remark '{canon}' not found.")

    # Count rows still using it so the UI can warn the user.
    used = await db.execute(text(
        "SELECT COUNT(*) FROM quarterly_results WHERE valuation = :v"
    ), {"v": canon})
    await invalidate_pe_analysis()
    return {"success": True, "value": canon, "rows_still_using": int(used.scalar() or 0)}


@router.post("/pe_analysis/bulk_ignore")
async def bulk_ignore_pe(body: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Mark multiple PE Pending rows as IGNORE in a single atomic transaction.

    Accepts {"row_ids": [1, 2, 3, ...]} where each ID is a quarterly_results.id.
    Only updates rows whose valuation is currently NULL/empty (pending), so rows
    that were reviewed between selection and action are safely skipped.
    """
    req_id = getattr(request.state, "request_id", None) if hasattr(request, "state") else None

    row_ids = body.get("row_ids")
    if not row_ids or not isinstance(row_ids, list):
        raise HTTPException(status_code=400, detail="row_ids must be a non-empty list")
    if len(row_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 rows per bulk operation")

    int_ids = []
    for rid in row_ids:
        try:
            int_ids.append(int(rid))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid row id: {rid}")

    # Fetch symbols for audit trail before the update
    pre_rows = await db.execute(text(
        "SELECT id, stock_symbol, valuation FROM quarterly_results WHERE id = ANY(:ids)"
    ), {"ids": int_ids})
    pre_map = {r.id: {"stock_symbol": r.stock_symbol, "valuation": r.valuation} for r in pre_rows.fetchall()}

    result = await db.execute(text("""
        UPDATE quarterly_results
        SET valuation = 'ignore',
            user_reviewed = TRUE,
            extraction_status = CASE
                WHEN extraction_status IN ('failed', 'error', 'pending')
                THEN 'completed' ELSE extraction_status
            END,
            updated_at = NOW(),
            reviewed_at = NOW()
        WHERE id = ANY(:ids)
          AND (valuation IS NULL OR valuation = '')
    """), {"ids": int_ids})

    # Propagate IGNORE to sibling rows (same resolved_symbol + quarter + FY)
    # so dual-listed / revised filing counterparts don't remain as ghost pending.
    if DEDUP_ENABLED and result.rowcount > 0:
        await db.execute(text(f"""
            UPDATE quarterly_results
            SET valuation = 'ignore', user_reviewed = TRUE, updated_at = NOW(),
                reviewed_at = COALESCE(reviewed_at, NOW()),
                extraction_status = CASE
                    WHEN extraction_status IN ('failed', 'error', 'pending')
                    THEN 'completed' ELSE extraction_status END
            WHERE (valuation IS NULL OR valuation = '')
              AND id NOT IN (SELECT UNNEST(:ids))
              AND EXISTS (
                  SELECT 1 FROM quarterly_results src
                  LEFT JOIN stocks ss1 ON ss1.symbol = src.stock_symbol
                  LEFT JOIN stocks ss2 ON ss2.bse_token = CASE
                      WHEN src.stock_symbol ~ '^\\d+$' THEN CAST(src.stock_symbol AS INT) END
                  LEFT JOIN stocks ts1 ON ts1.symbol = quarterly_results.stock_symbol
                  LEFT JOIN stocks ts2 ON ts2.bse_token = CASE
                      WHEN quarterly_results.stock_symbol ~ '^\\d+$'
                      THEN CAST(quarterly_results.stock_symbol AS INT) END
                  WHERE src.id = ANY(:ids)
                    AND ({_resolved_symbol_sql("src", "ss1", "ss2")})
                        = ({_resolved_symbol_sql("quarterly_results", "ts1", "ts2")})
                    AND src.quarter = quarterly_results.quarter
                    AND RIGHT(src.financial_year, 2) = RIGHT(quarterly_results.financial_year, 2)
              )
        """), {"ids": int_ids})

    await db.commit()

    updated = result.rowcount
    skipped = len(int_ids) - updated

    # Audit log: one entry per row that was actually updated
    for rid in int_ids:
        info = pre_map.get(rid, {})
        old_val = info.get("valuation")
        was_pending = not old_val or old_val == ""
        await log_pe_action(
            db,
            stock_symbol=info.get("stock_symbol", "UNKNOWN"),
            row_id=rid,
            action="bulk_ignore",
            old_valuation=old_val,
            new_valuation="IGNORE" if was_pending else None,
            old_fields=None,
            new_fields={"valuation": "ignore", "user_reviewed": True},
            outcome="success" if was_pending else "skipped",
            request_id=req_id,
        )

    await invalidate_pe_analysis()
    return {"success": True, "updated": updated, "skipped": skipped}


@router.get("/pe_analysis/audit_log")
async def get_pe_audit_log(
    db: AsyncSession = Depends(get_db),
    symbol: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
):
    """Query the PE audit log for forensic investigation."""
    conditions: list[str] = []
    params: dict = {}

    if symbol:
        conditions.append("stock_symbol = :symbol")
        params["symbol"] = symbol.upper()
    if action:
        conditions.append("action = :action")
        params["action"] = action
    if outcome:
        conditions.append("outcome = :outcome")
        params["outcome"] = outcome
    if date_from:
        try:
            df = datetime.strptime(date_from[:10], "%Y-%m-%d")
            conditions.append("created_at >= :date_from")
            params["date_from"] = df
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            conditions.append("created_at <= :date_to")
            params["date_to"] = dt
        except ValueError:
            pass

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    count_row = await db.execute(text(f"SELECT COUNT(*) FROM pe_audit_log {where_clause}"), params)
    total = count_row.scalar() or 0

    rows = await db.execute(text(f"""
        SELECT id, stock_symbol, row_id, action, old_valuation, new_valuation,
               old_fields, new_fields, outcome, error_detail, request_id, created_at
        FROM pe_audit_log
        {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)
    results = [dict(r._mapping) for r in rows.fetchall()]

    return {
        "results": results,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@router.get("/pe_analysis/filters")
async def get_pe_filters(db: AsyncSession = Depends(get_db)):
    """Get available filter options for PE analysis page."""
    cached_result = await cache_get("pe:filters")
    if cached_result:
        return cached_result

    years = await db.execute(text(
        "SELECT DISTINCT financial_year FROM quarterly_results WHERE financial_year IS NOT NULL ORDER BY financial_year DESC"
    ))
    quarters = await db.execute(text(
        "SELECT DISTINCT quarter FROM quarterly_results WHERE quarter IS NOT NULL ORDER BY quarter"
    ))
    exchanges = await db.execute(text(
        "SELECT DISTINCT exchange FROM quarterly_results WHERE exchange IS NOT NULL ORDER BY exchange"
    ))
    sectors = await db.execute(text(
        "SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL AND sector != '' ORDER BY sector"
    ))

    result = {
        "years": [r[0] for r in years.fetchall()],
        "quarters": [r[0] for r in quarters.fetchall()],
        "exchanges": [r[0] for r in exchanges.fetchall()],
        "sectors": [r[0] for r in sectors.fetchall()],
    }

    await cache_set("pe:filters", result, ttl=60)
    return result


@router.get("/pe_analysis/report_summary")
async def get_report_summary(
    db: AsyncSession = Depends(get_db),
    year: Optional[str] = Query(None),
    quarter: Optional[str] = Query(None),
    exchange: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
):
    """Aggregated analytics report — all computation server-side."""
    cache_key = f"report:summary:{year or ''}:{quarter or ''}:{exchange or ''}:{sector or ''}"
    cached_result = await cache_get(cache_key)
    if cached_result:
        return cached_result

    conditions = ["qr.valuation IS NOT NULL", "qr.valuation != ''", "(qr.extraction_status = 'completed' OR qr.user_reviewed = TRUE)"]
    params: dict = {}

    if year:
        fy_year = _fy_to_year(year)
        if fy_year:
            conditions.append("qr.financial_year ~ :fy_pattern")
            params["fy_pattern"] = f"(^|FY){fy_year % 100:02d}$|^{fy_year}$|{fy_year - 1}-{fy_year % 100:02d}$"
    if quarter:
        conditions.append("qr.quarter = :quarter")
        params["quarter"] = quarter
    if exchange:
        conditions.append("qr.exchange = :exchange")
        params["exchange"] = exchange
    if sector:
        conditions.append("COALESCE(s.sector, '') ILIKE :sector")
        params["sector"] = f"%{sector}%"

    where_clause = " AND ".join(conditions)

    rows = await db.execute(text(f"""
        SELECT DISTINCT ON (qr.stock_symbol)
            qr.stock_symbol, qr.company_name, qr.pe, qr.cmp, qr.valuation,
            qr.recommendation, qr.target_price, qr.financial_year, qr.quarter,
            qr.exchange, COALESCE(s.sector, 'Unknown') AS sector
        FROM quarterly_results qr
        LEFT JOIN stocks s ON s.symbol = qr.stock_symbol
        WHERE {where_clause}
        ORDER BY qr.stock_symbol, qr.financial_year DESC, qr.quarter DESC
    """), params)
    data = [dict(r._mapping) for r in rows.fetchall()]

    if not data:
        return {"summary": {}, "pe_distribution": [], "valuation_counts": {},
                "sector_summary": [], "top_cheapest": [], "top_expensive": []}

    pe_values = [r["pe"] for r in data if r["pe"] and r["pe"] > 0]
    avg_pe = sum(pe_values) / len(pe_values) if pe_values else 0
    sorted_pe = sorted(pe_values)
    median_pe = sorted_pe[len(sorted_pe) // 2] if sorted_pe else 0

    valuation_counts: dict = {}
    for r in data:
        v = canonicalize_valuation(r.get("valuation")) or "UNKNOWN"
        valuation_counts[v] = valuation_counts.get(v, 0) + 1

    buckets = [(0, 10), (10, 20), (20, 30), (30, 50), (50, 100), (100, 9999)]
    pe_distribution = []
    for lo, hi in buckets:
        label = f"{lo}-{hi}" if hi < 9999 else f"{lo}+"
        count = sum(1 for p in pe_values if lo <= p < hi)
        pe_distribution.append({"range": label, "count": count})

    sector_map: dict = {}
    for r in data:
        sec = r.get("sector") or "Unknown"
        if sec not in sector_map:
            sector_map[sec] = {"sector": sec, "count": 0, "pe_sum": 0, "cheap": 0, "expensive": 0}
        sector_map[sec]["count"] += 1
        if r["pe"]:
            sector_map[sec]["pe_sum"] += r["pe"]
        tone = valuation_tone(r.get("valuation"))
        if tone == VALUATION_TONE_BULLISH:
            sector_map[sec]["cheap"] += 1
        elif tone == VALUATION_TONE_BEARISH:
            sector_map[sec]["expensive"] += 1

    sector_summary = []
    for s in sector_map.values():
        s["avg_pe"] = s["pe_sum"] / s["count"] if s["count"] else 0
        del s["pe_sum"]
        sector_summary.append(s)
    sector_summary.sort(key=lambda x: x["count"], reverse=True)

    with_pe = [r for r in data if r["pe"] and r["pe"] > 0]
    top_cheapest = sorted(with_pe, key=lambda x: x["pe"])[:10]
    top_expensive = sorted(with_pe, key=lambda x: x["pe"], reverse=True)[:10]

    signal_counts: dict = {}
    for r in data:
        sig = r.get("recommendation") or ""
        if sig:
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

    result = {
        "summary": {"total": len(data), "avg_pe": avg_pe, "median_pe": median_pe},
        "pe_distribution": pe_distribution,
        "valuation_counts": valuation_counts,
        "signal_counts": signal_counts,
        "sector_summary": sector_summary,
        "top_cheapest": top_cheapest,
        "top_expensive": top_expensive,
    }

    await cache_set(cache_key, result, ttl=30)
    return result


@router.get("/pe_analysis/report_detail")
async def get_report_detail(
    db: AsyncSession = Depends(get_db),
    filter_type: str = Query("all"),
    filter_value: str = Query(""),
    year: Optional[str] = Query(None),
    quarter: Optional[str] = Query(None),
    exchange: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
):
    """Drill-down detail — returns stocks matching a specific filter slice."""
    conditions = ["qr.valuation IS NOT NULL", "qr.valuation != ''", "(qr.extraction_status = 'completed' OR qr.user_reviewed = TRUE)"]
    params: dict = {}

    if year:
        fy_year = _fy_to_year(year)
        if fy_year:
            conditions.append("qr.financial_year ~ :fy_pattern")
            params["fy_pattern"] = f"(^|FY){fy_year % 100:02d}$|^{fy_year}$|{fy_year - 1}-{fy_year % 100:02d}$"
    if quarter:
        conditions.append("qr.quarter = :quarter")
        params["quarter"] = quarter
    if exchange:
        conditions.append("qr.exchange = :exchange")
        params["exchange"] = exchange
    if sector:
        conditions.append("COALESCE(s.sector, '') ILIKE :sector_filter")
        params["sector_filter"] = f"%{sector}%"

    where_clause = " AND ".join(conditions)

    base_sql = f"""
        SELECT DISTINCT ON (qr.stock_symbol)
            qr.stock_symbol, qr.company_name, qr.pe, qr.cmp, qr.valuation,
            qr.recommendation, qr.target_price, qr.financial_year, qr.quarter,
            qr.exchange, qr.comments, qr.source_pdf_url,
            COALESCE(s.sector, 'Unknown') AS sector
        FROM quarterly_results qr
        LEFT JOIN stocks s ON s.symbol = qr.stock_symbol
        WHERE {where_clause}
        ORDER BY qr.stock_symbol, qr.financial_year DESC, qr.quarter DESC
    """

    rows = await db.execute(text(base_sql), params)
    all_data = [dict(r._mapping) for r in rows.fetchall()]

    if filter_type == "valuation" and filter_value:
        target = filter_value.upper()
        filtered = [r for r in all_data if
                    canonicalize_valuation(r.get("valuation")) == target or
                    (r.get("valuation") or "").upper() == target]
    elif filter_type == "pe_range" and filter_value:
        parts = filter_value.replace("+", "-9999").split("-")
        lo, hi = float(parts[0]), float(parts[1])
        filtered = [r for r in all_data if r.get("pe") and lo <= r["pe"] < hi]
    elif filter_type == "sector" and filter_value:
        filtered = [r for r in all_data if (r.get("sector") or "Unknown") == filter_value]
    elif filter_type == "signal" and filter_value:
        filtered = [r for r in all_data if (r.get("recommendation") or "") == filter_value]
    else:
        filtered = all_data

    total = len(filtered)
    offset = (page - 1) * per_page
    page_data = filtered[offset:offset + per_page]

    return {
        "results": page_data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


@router.get("/pe_formulas")
async def get_pe_formulas(db: AsyncSession = Depends(get_db)):
    """Get all PE formulas."""
    rows = await db.execute(text("SELECT * FROM pe_formulas ORDER BY is_default DESC, name"))
    return {"formulas": [dict(r._mapping) for r in rows.fetchall()]}


@router.post("/pe_formulas")
async def create_pe_formula(body: dict, db: AsyncSession = Depends(get_db)):
    """Create a new PE formula."""
    result = await db.execute(text("""
        INSERT INTO pe_formulas (name, q1_expr, q2_expr, q3_expr, q4_expr, is_default)
        VALUES (:name, :q1, :q2, :q3, :q4, false)
        RETURNING id
    """), {
        "name": body["name"],
        "q1": body.get("q1_expr", "Q1*4"),
        "q2": body.get("q2_expr", "(Q1+Q2)*2"),
        "q3": body.get("q3_expr", "(Q1+Q2+Q3)*4/3"),
        "q4": body.get("q4_expr", "FY"),
    })
    await db.commit()
    return {"success": True, "id": result.scalar()}


@router.put("/pe_formulas/{formula_id}/activate")
async def activate_formula(formula_id: int, db: AsyncSession = Depends(get_db)):
    """Set a formula as the default."""
    await db.execute(text("UPDATE pe_formulas SET is_default = false"))
    await db.execute(text("UPDATE pe_formulas SET is_default = true WHERE id = :id"), {"id": formula_id})
    await db.commit()
    await invalidate_pe_analysis()
    return {"success": True}


@router.post("/pe_analysis/{symbol}/retrigger")
async def retrigger_pe_extraction(
    symbol: str,
    row_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-queue PDF extraction for a stock row.

    - With ?row_id=N: retriggers that exact row.
    - Without row_id: retriggers the latest row for that stock_symbol.

    Marks the row as 'pending', clears the previous error, and dispatches a fresh
    Celery task. Useful when an extraction failed (OpenAI quota, parse error, network)
    or returned partial data.
    """
    if row_id is not None:
        row = await db.execute(text("""
            SELECT id, stock_symbol, source_pdf_url, exchange, company_name, announcement_date
            FROM quarterly_results
            WHERE id = :rid AND stock_symbol = :sym
            LIMIT 1
        """), {"rid": row_id, "sym": symbol})
    else:
        row = await db.execute(text("""
            SELECT id, stock_symbol, source_pdf_url, exchange, company_name, announcement_date
            FROM quarterly_results
            WHERE stock_symbol = :sym
            ORDER BY COALESCE(announcement_date, created_at) DESC, id DESC
            LIMIT 1
        """), {"sym": symbol})

    found = row.first()
    if not found:
        raise HTTPException(status_code=404, detail=f"No row found for {symbol}")
    if not found.source_pdf_url:
        raise HTTPException(
            status_code=400,
            detail=f"{symbol} has no source PDF URL — cannot retrigger; upload PDF manually.",
        )

    # Mark current row as pending, clear previous error, kick off the task.
    await db.execute(text("""
        UPDATE quarterly_results
        SET extraction_status = 'pending',
            extraction_error = NULL,
            updated_at = NOW()
        WHERE id = :rid
    """), {"rid": found.id})
    await db.commit()

    task = run_quarterly_extraction.delay(
        stock_symbol=found.stock_symbol,
        pdf_url=found.source_pdf_url,
        exchange=found.exchange or "BSE",
        company_name=found.company_name or "",
        announcement_date=str(found.announcement_date) if found.announcement_date else None,
    )

    await invalidate_pe_analysis()

    return {
        "success": True,
        "row_id": found.id,
        "symbol": found.stock_symbol,
        "task_id": task.id,
        "status": "queued",
    }


@router.delete("/pe_analysis/{symbol}")
async def delete_pe_analysis(symbol: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Delete all quarterly results for a stock."""
    req_id = getattr(request.state, "request_id", None) if hasattr(request, "state") else None

    result = await db.execute(
        text("DELETE FROM quarterly_results WHERE stock_symbol = :sym"),
        {"sym": symbol},
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

    await log_pe_action(
        db, symbol, row_id=None, action="delete_stock",
        old_valuation=None, new_valuation=None,
        old_fields={"rows_deleted": result.rowcount}, new_fields=None,
        outcome="success", request_id=req_id,
    )

    await invalidate_pe_analysis()
    return {"success": True, "deleted": result.rowcount}


@router.put("/pe_analysis/{symbol}")
async def update_pe_analysis(
    symbol: str,
    body: dict,
    request: Request,
    row_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Update valuation/recommendation/comments/cmp/pe etc for a stock.

    `row_id` (query param) — when provided, updates that exact quarterly_results
    row. The frontend always passes it now so SKIP / Edit always hit the row
    that is currently visible on the page (otherwise we may silently update a
    different FY/quarter row for the same stock, e.g. when Q4 is already
    reviewed but the user is acting on the Q3 PENDING row).

    Fallback (no row_id) keeps the legacy "latest row" behavior so any older
    callers / scripts keep working.
    """
    req_id = getattr(request.state, "request_id", None) if hasattr(request, "state") else None

    allowed_fields = [
        "valuation", "recommendation", "comments", "target_price",
        "manual_fy_eps", "manual_fy_eps_formula", "cmp", "pe",
    ]
    updates = {k: v for k, v in body.items() if k in allowed_fields and v is not None}

    if "valuation" in updates and updates["valuation"]:
        canon = canonicalize_valuation(str(updates["valuation"]))
        if canon and canon not in VALUATION_VALUES:
            # Allow if it matches a user-defined custom remark.
            row = await db.execute(text(
                "SELECT 1 FROM custom_valuations WHERE value = :v"
            ), {"v": canon})
            if row.first() is None:
                allowed = sorted(VALUATION_VALUES)
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid valuation '{updates['valuation']}'. "
                           f"Allowed built-ins: {allowed}, or any registered custom remark.",
                )
        updates["valuation"] = canon

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    # Fetch current state BEFORE the update for audit trail
    old_row: dict = {}
    if row_id is not None:
        cur = await db.execute(text(
            "SELECT id, valuation, recommendation, cmp, pe, user_reviewed, comments, target_price "
            "FROM quarterly_results WHERE id = :rid AND stock_symbol = :sym"
        ), {"rid": row_id, "sym": symbol})
    else:
        cur = await db.execute(text(
            "SELECT id, valuation, recommendation, cmp, pe, user_reviewed, comments, target_price "
            "FROM quarterly_results WHERE stock_symbol = :sym "
            "ORDER BY financial_year DESC, quarter DESC, id DESC LIMIT 1"
        ), {"sym": symbol})
    cur_row = cur.first()
    if cur_row:
        old_row = dict(cur_row._mapping)
        if row_id is None:
            row_id = old_row.get("id")

    # When a valuation is assigned, mark user_reviewed so the row appears
    # on PE Reviewed immediately (even if extraction is still processing).
    # Also auto-promote extraction_status for failed/error/pending rows.
    promote_status = False
    if "valuation" in updates and updates["valuation"]:
        promote_status = True

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    if promote_status:
        set_clause += ", user_reviewed = TRUE"
        set_clause += ", extraction_status = CASE WHEN extraction_status IN ('failed', 'error', 'pending') THEN 'completed' ELSE extraction_status END"
        set_clause += ", reviewed_at = CASE WHEN reviewed_at IS NULL THEN NOW() ELSE reviewed_at END"
    elif "valuation" in updates and not updates["valuation"]:
        set_clause += ", reviewed_at = NULL"
    updates["sym"] = symbol

    if row_id is not None:
        updates["rid"] = row_id
        result = await db.execute(text(f"""
            UPDATE quarterly_results SET {set_clause}, updated_at = NOW()
            WHERE id = :rid AND stock_symbol = :sym
        """), updates)
        if result.rowcount == 0:
            await log_pe_action(
                db, symbol, row_id, action="update_fields",
                old_valuation=old_row.get("valuation"),
                new_valuation=updates.get("valuation"),
                old_fields=old_row, new_fields={k: v for k, v in updates.items() if k not in ("sym", "rid")},
                outcome="failed", error_detail=f"No row found for {symbol} with id={row_id}",
                request_id=req_id,
            )
            raise HTTPException(
                status_code=404,
                detail=f"No row found for {symbol} with id={row_id}",
            )
    else:
        result = await db.execute(text(f"""
            UPDATE quarterly_results SET {set_clause}, updated_at = NOW()
            WHERE stock_symbol = :sym
            AND id = (
                SELECT id FROM quarterly_results
                WHERE stock_symbol = :sym
                ORDER BY financial_year DESC, quarter DESC, id DESC
                LIMIT 1
            )
        """), updates)
        if result.rowcount == 0:
            await log_pe_action(
                db, symbol, None, action="update_fields",
                old_valuation=None, new_valuation=updates.get("valuation"),
                old_fields=None, new_fields={k: v for k, v in updates.items() if k != "sym"},
                outcome="failed", error_detail=f"No row found for {symbol}",
                request_id=req_id,
            )
            raise HTTPException(
                status_code=404,
                detail=f"No row found for {symbol}",
            )
    # Propagate valuation to sibling rows (same resolved_symbol + quarter + FY)
    # so revised filings and dual-listed counterparts don't stay as ghost pending.
    propagated = 0
    if DEDUP_ENABLED and promote_status and row_id is not None:
        # Fetch the row's quarter/FY for propagation scope
        prop_row = await db.execute(text(
            "SELECT quarter, financial_year FROM quarterly_results WHERE id = :rid"
        ), {"rid": row_id})
        prop_data = prop_row.first()
        if prop_data:
            prop_result = await db.execute(text("""
                UPDATE quarterly_results
                SET valuation = :val, user_reviewed = TRUE, updated_at = NOW(),
                    reviewed_at = COALESCE(reviewed_at, NOW()),
                    extraction_status = CASE
                        WHEN extraction_status IN ('failed', 'error', 'pending')
                        THEN 'completed' ELSE extraction_status END
                WHERE (valuation IS NULL OR valuation = '')
                  AND quarter = :q
                  AND RIGHT(financial_year, 2) = RIGHT(:fy, 2)
                  AND id != :rid
                  AND stock_symbol IN (
                      SELECT qr2.stock_symbol FROM quarterly_results qr2
                      LEFT JOIN stocks ss1 ON ss1.symbol = qr2.stock_symbol
                      LEFT JOIN stocks ss2 ON ss2.bse_token = CASE
                          WHEN qr2.stock_symbol ~ '^\\d+$' THEN CAST(qr2.stock_symbol AS INT) END
                      WHERE qr2.id = :rid
                      UNION
                      SELECT qr3.stock_symbol FROM quarterly_results qr3
                      LEFT JOIN stocks ss3 ON ss3.symbol = qr3.stock_symbol
                      LEFT JOIN stocks ss4 ON ss4.bse_token = CASE
                          WHEN qr3.stock_symbol ~ '^\\d+$' THEN CAST(qr3.stock_symbol AS INT) END
                      WHERE ({_resolved_symbol_sql("qr3", "ss3", "ss4")}) = (
                          SELECT {_resolved_symbol_sql("qr4", "ss5", "ss6")}
                          FROM quarterly_results qr4
                          LEFT JOIN stocks ss5 ON ss5.symbol = qr4.stock_symbol
                          LEFT JOIN stocks ss6 ON ss6.bse_token = CASE
                              WHEN qr4.stock_symbol ~ '^\\d+$' THEN CAST(qr4.stock_symbol AS INT) END
                          WHERE qr4.id = :rid
                      )
                  )
            """), {
                "val": updates.get("valuation"),
                "q": prop_data.quarter,
                "fy": prop_data.financial_year,
                "rid": row_id,
            })
            propagated = prop_result.rowcount

    await db.commit()

    # Determine audit action type
    new_val = updates.get("valuation")
    if new_val and not old_row.get("valuation"):
        audit_action = "set_valuation"
    elif not new_val and "valuation" in updates:
        audit_action = "clear_valuation"
    elif new_val and old_row.get("valuation") and new_val != old_row.get("valuation"):
        audit_action = "change_valuation"
    else:
        audit_action = "update_fields"

    await log_pe_action(
        db, symbol, row_id, action=audit_action,
        old_valuation=old_row.get("valuation"),
        new_valuation=new_val,
        old_fields=old_row,
        new_fields={k: v for k, v in updates.items() if k not in ("sym", "rid")},
        outcome="success",
        request_id=req_id,
    )

    # Update sector/sub_sector in stocks table if provided
    stock_updates = {k: v for k, v in body.items() if k in ("sector", "sub_sector") and v is not None}
    if stock_updates:
        set_stock = ", ".join(f"{k} = :{k}" for k in stock_updates)
        stock_updates["sym"] = symbol
        await db.execute(text(f"UPDATE stocks SET {set_stock} WHERE symbol = :sym"), stock_updates)
        await db.commit()

    await invalidate_pe_analysis()
    return {"success": True, "updated_row_id": row_id}
