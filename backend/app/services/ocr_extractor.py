"""
OCR + AI extraction service.
Extracted from: nse_url_test.py (run_quarterly_extraction, _upsert_quarterly_result,
    _insert_extraction_placeholder, _auto_fetch_cmp_for_stock)
"""

import logging
import io
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from ..database import get_db_session
from ..config import get_settings
from ..cache_keys import invalidate_pe_analysis

logger = logging.getLogger(__name__)
settings = get_settings()


_NUM_STRIP_RE = re.compile(r"[,\s\u20b9$€£%]")


# ─── Shared HTTP client for OpenAI (per event loop) ─────────────────────────
# Reusing one httpx.AsyncClient across requests reuses TLS sessions + TCP
# connections. Critical when running 8+ concurrent extractions: a fresh client
# per call adds ~150-300ms TLS handshake. Singleton-per-loop is safe under
# Celery --pool=threads (each thread owns its own loop).
_openai_clients_per_loop: dict[int, httpx.AsyncClient] = {}


def _get_openai_client() -> httpx.AsyncClient:
    """Return (or create) the httpx.AsyncClient bound to the current event loop."""
    import asyncio
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = 0
    client = _openai_clients_per_loop.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=30,
                                 keepalive_expiry=60.0),
            http2=False,  # OpenAI accepts HTTP/1.1 keepalive — HTTP/2 needs `httpx[http2]`
        )
        _openai_clients_per_loop[loop_id] = client
    return client


async def close_openai_clients() -> None:
    """Close all per-loop OpenAI clients (call on shutdown)."""
    for c in list(_openai_clients_per_loop.values()):
        try:
            await c.aclose()
        except Exception:
            pass
    _openai_clients_per_loop.clear()
_NULL_STRINGS = frozenset({
    "", "-", "--", "—", "–", "n/a", "na", "n.a.", "n.a", "nm", "n.m.",
    "nil", "null", "none", "not applicable", "not available",
})


def _to_float(v: Any) -> Optional[float]:
    """
    Coerce an AI-extracted numeric value to float (or None).
    Handles Indian quarterly-result quirks:
      - "(0.17)" / "(1,234.56)"  -> -0.17 / -1234.56  (accounting notation for negatives)
      - "1,234.56"               -> 1234.56
      - "₹1,234"                 -> 1234.0
      - "-", "NA", "NM", "—"     -> None
      - already int/float        -> float(v)
    Returns None on any unrecognised input (instead of crashing the DB INSERT).
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.lower() in _NULL_STRINGS:
        return None
    s = _NUM_STRIP_RE.sub("", s)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _normalize_periods(periods: List[Dict]) -> None:
    """Coerce all numeric fields in each period dict to float-or-None, in place."""
    for p in periods or []:
        for k in ("eps_basic", "eps_diluted",
                  "revenue", "profit_before_tax", "profit_after_tax",
                  "total_income", "total_expenses"):
            if k in p:
                p[k] = _to_float(p[k])


_FINANCIAL_KEYWORDS = (
    "revenue", "expense", "tax", "profit", "earning",
    "income", "eps", "share capital", "diluted", "comprehensive",
    "quarter ended", "year ended",
)
_MIN_KEYWORD_MATCHES = 2
_MAX_PAGES_TO_AI = 8
_MAX_PAGES_SCAN = 25


def _render_pages_to_png(pdf_bytes: bytes, page_indices: List[int], zoom: float = 2.0) -> List[bytes]:
    """Render given PDF page indices (0-based) to PNG bytes via PyMuPDF."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out: List[bytes] = []
    mat = fitz.Matrix(zoom, zoom)
    for idx in page_indices:
        if idx < 0 or idx >= doc.page_count:
            continue
        try:
            pix = doc.load_page(idx).get_pixmap(matrix=mat, alpha=False)
            out.append(pix.tobytes("png"))
        except Exception as e:
            logger.warning(f"Page {idx} render failed: {e}")
    doc.close()
    return out


async def download_pdf_bytes(pdf_url: str) -> Optional[bytes]:
    """Download PDF with BSE-friendly headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.bseindia.com/",
    }
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(pdf_url, headers=headers)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.error(f"PDF download failed ({pdf_url}): {e}")
        return None


def _select_financial_pages(pdf_bytes: bytes) -> tuple:
    """Return (filtered_page_indices, total_pages, has_text_layer)."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = doc.page_count
    filtered: List[int] = []
    text_pages = 0
    for idx in range(min(total, _MAX_PAGES_SCAN)):
        try:
            text = doc.load_page(idx).get_text("text")
        except Exception:
            continue
        if text.strip():
            text_pages += 1
        text_lower = text.lower()
        hits = sum(1 for kw in _FINANCIAL_KEYWORDS if kw in text_lower)
        if hits >= _MIN_KEYWORD_MATCHES:
            filtered.append(idx)
    doc.close()
    has_text = text_pages > 0
    return filtered, total, has_text


async def download_and_convert_pdf(pdf_url: str) -> List[bytes]:
    """
    Download PDF and select financial-relevant pages.
    Strategy (mirrors old app):
      - Has text layer: keyword-filter pages (2+ matches), cap at 8
      - No text layer (image PDF): first 6 pages
      - No keyword pages found but text exists: try first 6 pages as fallback
    """
    pdf_bytes = await download_pdf_bytes(pdf_url)
    if pdf_bytes is None:
        return []

    try:
        filtered, total, has_text = _select_financial_pages(pdf_bytes)
    except Exception as e:
        logger.error(f"PDF page-selection failed: {e}")
        return []

    if has_text and filtered:
        page_indices = filtered[:_MAX_PAGES_TO_AI]
        mode = "keyword"
    else:
        page_indices = list(range(min(total, 6)))
        mode = "fallback" if has_text else "image-pdf"

    images = _render_pages_to_png(pdf_bytes, page_indices)
    logger.info(
        f"PDF: {total} pages total, {len(filtered)} keyword-matched, "
        f"selected {len(images)} ({mode})"
    )
    return images


async def download_and_convert_pdf_full(pdf_url: str, max_pages: int = 12) -> List[bytes]:
    """Fallback: download and render the FIRST max_pages without keyword filtering."""
    pdf_bytes = await download_pdf_bytes(pdf_url)
    if pdf_bytes is None:
        return []
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n = min(doc.page_count, max_pages)
    doc.close()
    images = _render_pages_to_png(pdf_bytes, list(range(n)))
    logger.info(f"PDF (full fallback): {n} pages rendered")
    return images


_BASE_PROMPT = """You are extracting data from an Indian company's quarterly financial results PDF.

The document may have TWO tables: Standalone and Consolidated (check the title of each table).

**TABLE STRUCTURE:**
Each table typically has 4-6+ data columns:
- 3 columns under "Quarter ended" header (individual quarterly periods)
- 0-2 columns under "Six Month ended" / "Nine Month ended" header (cumulative periods — NOT always present)
- 1 column under "Year Ended" header (full year annual data)
You MUST extract ALL columns as separate entries — quarterly, cumulative, AND annual.

**ROW STRUCTURE (top to bottom in each table):**
Row 1: "Revenue from Operations" — this is the FIRST income row
Row 2: "Other Income" — this is the SECOND income row (separate from Revenue)
Row 3: "Total Income" — sum row
Then expense rows, then profit rows, then tax, then EPS at bottom.

**CRITICAL — DASH HANDLING:**
- A dash (-) means null. Return null, not 0, not 0.0.

**face_value:** Read from the row label text "Face Value Rs. X/- Each".

**Quarter & Financial Year mapping (Indian FY):**
- June ending → Q1, FY = next March's year
- September ending → Q2, FY = next March's year
- December ending → Q3, FY = next March's year
- March ending → Q4, FY = same year
- Year Ended column → period_type = "annual", quarter = "FY"

**period_type mapping for cumulative columns:**
- "Six Month ended" column → period_type = "six_month", quarter = same as matching quarterly date (Q2)
- "Nine Month ended" column → period_type = "nine_month", quarter = same as matching quarterly date (Q3)
- These are FULL entries with ALL rows extracted (revenue, expenses, PAT, EPS, etc.), same schema as quarterly entries.

IMPORTANT: Return ONLY raw JSON. No markdown, no code blocks.
If a page is NOT a financial results table, IGNORE it completely.

{
    "company_name": "string",
    "units": "lakhs or crores",
    "standalone_periods": [
        {
            "column_header": "30.06.2025",
            "period_type": "quarter | six_month | nine_month | annual",
            "quarter": "Q1",
            "financial_year": "2026",
            "revenue_from_operations": number_or_null,
            "other_income": number_or_null,
            "total_income": number_or_null,
            "total_expenses": number_or_null,
            "profit_before_exceptional": number_or_null,
            "exceptional_items": number_or_null,
            "profit_before_tax": number_or_null,
            "tax_expense": number_or_null,
            "profit_after_tax": number_or_null,
            "profit_attributable_to_minority": number_or_null,
            "other_comprehensive_income": number_or_null,
            "total_comprehensive_income": number_or_null,
            "paid_up_equity_share_capital": number_or_null,
            "face_value": number_or_null,
            "eps_basic": number_or_null,
            "eps_diluted": number_or_null
        }
    ],
    "consolidated_periods": []
}

Rules:
- Extract EVERY data column as a separate entry: quarterly columns + cumulative columns (six_month/nine_month) + annual column.
- A Q3 PDF typically has: 3 quarterly + 2 nine_month + 1 annual = 6 entries per table.
- A Q2 PDF typically has: 3 quarterly + 2 six_month + 1 annual = 6 entries per table.
- null for dash (-) or blank cells. Never use 0 or 0.0 for dashes.
- Return numbers exactly as printed in the document."""


_STEP_BY_STEP = (
    "\nSTEP-BY-STEP EXTRACTION:\n"
    "1. Each image = one table (Standalone or Consolidated). Identify which from the title.\n"
    "2. Locate ALL data columns: quarterly + cumulative (Six/Nine Month ended) + annual (Year Ended).\n"
    "3. For EACH column (including cumulative), extract ALL rows as a full entry with the correct period_type.\n"
    "4. Cumulative columns get period_type 'six_month' or 'nine_month', with quarter matching the date.\n"
    "5. Do NOT skip any column. Do NOT skip the Year Ended column.\n"
    "6. VERIFY per column: Total Income ≈ Revenue + Other Income."
)


async def extract_financial_data_ai(
    images: List[bytes],
    stock_symbol: str,
    company_name: str,
) -> Optional[Dict]:
    """
    Send financial-page images to OpenAI Vision (gpt-4.1-mini) to extract
    standalone_periods + consolidated_periods (full schema, matches old app).
    """
    import base64
    import json

    if not settings.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not configured")
        return None

    if not images:
        logger.error(f"No images to send for {stock_symbol}")
        return None

    content = [{"type": "text", "text": _BASE_PROMPT}]
    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    content.append({"type": "text", "text": _STEP_BY_STEP})

    try:
        client = _get_openai_client()
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4.1-mini",
                "messages": [{"role": "user", "content": content}],
                "temperature": 0,
                "max_tokens": 16000,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        logger.info(
            f"OpenAI vision for {stock_symbol}: prompt_tokens={usage.get('prompt_tokens')}, "
            f"completion_tokens={usage.get('completion_tokens')}, images={len(images)}"
        )
        ai_content = data["choices"][0]["message"].get("content")
        if not ai_content:
            logger.error(f"OpenAI returned empty content for {stock_symbol}")
            return None
        return json.loads(ai_content)
    except Exception as e:
        logger.error(f"OpenAI extraction failed for {stock_symbol}: {e}")
        return None


def _derive_quarter(period_ended: Optional[str], financial_year: Optional[str]) -> Optional[str]:
    """Derive quarter (Q1-Q4) from period_ended date string when AI returns null.
    Indian FY: April-March. Q1=Apr-Jun, Q2=Jul-Sep, Q3=Oct-Dec, Q4=Jan-Mar."""
    if not period_ended:
        return None
    import re
    pe_lower = period_ended.lower()
    month_name_map = {
        "march": "Q4", "mar": "Q4",
        "june": "Q1", "jun": "Q1",
        "september": "Q2", "sep": "Q2", "sept": "Q2",
        "december": "Q3", "dec": "Q3",
    }
    for key, q in month_name_map.items():
        if key in pe_lower:
            return q
    # Handle numeric dates like 31-03-2026, 2026-03-31, 31/03/2026
    m = re.search(r'(\d{1,4})[-/.](\d{1,2})[-/.](\d{2,4})', period_ended)
    if m:
        parts = [int(m.group(i)) for i in (1, 2, 3)]
        if parts[0] > 31:
            mm = parts[1]
        elif parts[1] > 12:
            mm = parts[0]
        else:
            mm = parts[1] if parts[0] > 12 else parts[1]
        month_q = {3: "Q4", 6: "Q1", 9: "Q2", 12: "Q3"}
        if mm in month_q:
            return month_q[mm]
    return None


def _parse_period_date(column_header: str) -> datetime:
    """Parse column_header like '30.06.2025' / 'March 31, 2026' to datetime for sorting."""
    if not column_header:
        return datetime.min
    s = str(column_header).strip()
    for fmt in (
        "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y",
        "%dst %B %Y", "%dnd %B %Y", "%drd %B %Y", "%dth %B %Y",
        "%dst %B, %Y", "%dnd %B, %Y", "%drd %B, %Y", "%dth %B, %Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.min


def _calculate_full_year_eps(periods: List[Dict], eps_key: str = "eps_basic") -> Dict:
    """Compute FY EPS estimate.
    Q1 -> Q1*4 | Q2 -> N6*2 or (Q1+Q2)*2 | Q3 -> N9*4/3 or sum*4/n | Q4/FY -> annual."""
    if not periods:
        return {}

    quarterly = [p for p in periods if p.get("period_type") == "quarter"]
    annual = [p for p in periods if p.get("period_type") == "annual"]
    nine_month = [p for p in periods if p.get("period_type") == "nine_month"]
    six_month = [p for p in periods if p.get("period_type") == "six_month"]

    if not quarterly and not annual:
        return {}

    quarterly.sort(key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True)
    latest = quarterly[0] if quarterly else None
    current_q = (latest.get("quarter") or "").upper() if latest else None
    current_fy = latest.get("financial_year", "") if latest else None

    cum_eps = None
    if current_q == "Q3" and nine_month:
        nm = sorted(
            [p for p in nine_month if p.get("financial_year") == current_fy],
            key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True,
        )
        if nm:
            cum_eps = nm[0].get(eps_key)
    elif current_q == "Q2" and six_month:
        sm = sorted(
            [p for p in six_month if p.get("financial_year") == current_fy],
            key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True,
        )
        if sm:
            cum_eps = sm[0].get(eps_key)

    same_fy = {}
    for p in quarterly:
        if p.get("financial_year") == current_fy:
            q = (p.get("quarter") or "").upper()
            eps = p.get(eps_key)
            if eps is not None and q:
                same_fy[q] = eps

    fy_eps = None
    for a in annual:
        if a.get("financial_year") == current_fy:
            fy_eps = a.get(eps_key)
            break

    result = {"current_quarter": current_q, "financial_year": current_fy, "formula": None, "value": None}

    if current_q == "Q4" or (not current_q and fy_eps is not None):
        result["formula"] = "FY"
        result["value"] = fy_eps
    elif current_q == "Q1":
        q1 = same_fy.get("Q1")
        if q1 is not None:
            result["formula"] = "Q1*4"
            result["value"] = round(q1 * 4, 4)
    elif current_q == "Q2":
        if cum_eps is not None:
            result["formula"] = "N6*2"
            result["value"] = round(cum_eps * 2, 4)
        else:
            q1, q2 = same_fy.get("Q1"), same_fy.get("Q2")
            if q1 is not None and q2 is not None:
                result["formula"] = "(Q1+Q2)*2"
                result["value"] = round((q1 + q2) * 2, 4)
            elif q2 is not None:
                result["formula"] = "Q2*4"
                result["value"] = round(q2 * 4, 4)
    elif current_q == "Q3":
        if cum_eps is not None:
            result["formula"] = "N9*4/3"
            result["value"] = round(cum_eps * 4 / 3, 4)
        else:
            vals = [same_fy.get(q) for q in ("Q1", "Q2", "Q3")]
            available = [v for v in vals if v is not None]
            if available:
                n = len(available)
                result["formula"] = f"sum({n}Q)*4/{n}"
                result["value"] = round(sum(available) * 4 / n, 4)
    elif current_q == "FY":
        result["formula"] = "FY"
        result["value"] = fy_eps

    return result


def _compute_all_fy_eps(ai_response: Dict) -> Dict:
    """Compute fy_eps for all 4 combos."""
    s = ai_response.get("standalone_periods", []) or []
    c = ai_response.get("consolidated_periods", []) or []
    return {
        "fy_eps_basic_standalone": _calculate_full_year_eps(s, "eps_basic"),
        "fy_eps_diluted_standalone": _calculate_full_year_eps(s, "eps_diluted"),
        "fy_eps_basic_consolidated": _calculate_full_year_eps(c, "eps_basic"),
        "fy_eps_diluted_consolidated": _calculate_full_year_eps(c, "eps_diluted"),
    }


def _parse_announcement_date(announcement_date) -> Optional[datetime]:
    """Parse BSE announcement_date (string or datetime) to datetime for asyncpg timestamptz."""
    if announcement_date is None or announcement_date == "":
        return None
    if isinstance(announcement_date, datetime):
        return announcement_date
    s = str(announcement_date).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d", "%d-%b-%Y %H:%M:%S", "%d %b %Y %H:%M:%S",
        "%d-%b-%Y", "%d %b %Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    logger.warning(f"Could not parse announcement_date '{announcement_date}'")
    return None


_QR_UPSERT_SQL = text("""
    INSERT INTO quarterly_results (
        stock_symbol, company_name, quarter, financial_year, period_ended,
        eps_basic_standalone, eps_diluted_standalone,
        eps_basic_consolidated, eps_diluted_consolidated,
        fy_eps_basic_standalone, fy_eps_diluted_standalone,
        fy_eps_basic_consolidated, fy_eps_diluted_consolidated,
        fy_eps_formula_standalone, fy_eps_formula_consolidated,
        cumulative_eps_basic_standalone, cumulative_eps_diluted_standalone,
        cumulative_eps_basic_consolidated, cumulative_eps_diluted_consolidated,
        standalone_data, consolidated_data, raw_ai_response,
        source_pdf_url, exchange, units,
        extraction_status, announcement_date, created_at, updated_at
    ) VALUES (
        :sym, :cn, :q, :fy, :pe,
        :ebs, :eds, :ebc, :edc,
        :fy_eb_s, :fy_ed_s, :fy_eb_c, :fy_ed_c,
        :fy_form_s, :fy_form_c,
        :cum_eb_s, :cum_ed_s, :cum_eb_c, :cum_ed_c,
        :sd, :cd, :rar,
        :pdf, :ex, :units,
        'completed', :ann_date, :now, :now
    )
    ON CONFLICT (stock_symbol, quarter, financial_year, announcement_date)
    DO UPDATE SET
        company_name = COALESCE(NULLIF(EXCLUDED.company_name, ''), quarterly_results.company_name),
        period_ended = COALESCE(NULLIF(EXCLUDED.period_ended, ''), quarterly_results.period_ended),
        units = COALESCE(NULLIF(EXCLUDED.units, ''), quarterly_results.units),
        source_pdf_url = COALESCE(NULLIF(EXCLUDED.source_pdf_url, ''), quarterly_results.source_pdf_url),
        eps_basic_standalone = COALESCE(EXCLUDED.eps_basic_standalone, quarterly_results.eps_basic_standalone),
        eps_diluted_standalone = COALESCE(EXCLUDED.eps_diluted_standalone, quarterly_results.eps_diluted_standalone),
        eps_basic_consolidated = COALESCE(EXCLUDED.eps_basic_consolidated, quarterly_results.eps_basic_consolidated),
        eps_diluted_consolidated = COALESCE(EXCLUDED.eps_diluted_consolidated, quarterly_results.eps_diluted_consolidated),
        fy_eps_basic_standalone = COALESCE(EXCLUDED.fy_eps_basic_standalone, quarterly_results.fy_eps_basic_standalone),
        fy_eps_diluted_standalone = COALESCE(EXCLUDED.fy_eps_diluted_standalone, quarterly_results.fy_eps_diluted_standalone),
        fy_eps_basic_consolidated = COALESCE(EXCLUDED.fy_eps_basic_consolidated, quarterly_results.fy_eps_basic_consolidated),
        fy_eps_diluted_consolidated = COALESCE(EXCLUDED.fy_eps_diluted_consolidated, quarterly_results.fy_eps_diluted_consolidated),
        fy_eps_formula_standalone = COALESCE(EXCLUDED.fy_eps_formula_standalone, quarterly_results.fy_eps_formula_standalone),
        fy_eps_formula_consolidated = COALESCE(EXCLUDED.fy_eps_formula_consolidated, quarterly_results.fy_eps_formula_consolidated),
        cumulative_eps_basic_standalone = COALESCE(EXCLUDED.cumulative_eps_basic_standalone, quarterly_results.cumulative_eps_basic_standalone),
        cumulative_eps_diluted_standalone = COALESCE(EXCLUDED.cumulative_eps_diluted_standalone, quarterly_results.cumulative_eps_diluted_standalone),
        cumulative_eps_basic_consolidated = COALESCE(EXCLUDED.cumulative_eps_basic_consolidated, quarterly_results.cumulative_eps_basic_consolidated),
        cumulative_eps_diluted_consolidated = COALESCE(EXCLUDED.cumulative_eps_diluted_consolidated, quarterly_results.cumulative_eps_diluted_consolidated),
        standalone_data = COALESCE(EXCLUDED.standalone_data, quarterly_results.standalone_data),
        consolidated_data = COALESCE(EXCLUDED.consolidated_data, quarterly_results.consolidated_data),
        raw_ai_response = COALESCE(EXCLUDED.raw_ai_response, quarterly_results.raw_ai_response),
        extraction_status = 'completed',
        extraction_error = NULL,
        updated_at = :now
    RETURNING id
""")


async def save_quarterly_result(
    stock_symbol: str,
    company_name: str,
    exchange: str,
    pdf_url: str,
    announcement_date,
    extraction_data: Dict,
) -> List[int]:
    """
    Process AI response with standalone_periods + consolidated_periods arrays.
    Builds period_map (quarterly + annual rows), injects cumulative EPS,
    computes FY-EPS estimates, and UPSERTs one row per (quarter, financial_year).
    Returns list of inserted/updated row IDs.
    """
    import json

    if not extraction_data:
        raise ValueError(f"AI extraction returned empty for {stock_symbol}")

    ai_company_name = extraction_data.get("company_name") or company_name
    units = extraction_data.get("units")
    standalone_periods = extraction_data.get("standalone_periods") or []
    consolidated_periods = extraction_data.get("consolidated_periods") or []

    if not standalone_periods and not consolidated_periods:
        if extraction_data.get("eps_basic_standalone") is not None or \
           extraction_data.get("eps_diluted_standalone") is not None or \
           extraction_data.get("eps_basic_consolidated") is not None or \
           extraction_data.get("eps_diluted_consolidated") is not None:
            standalone_periods = [{
                "column_header": extraction_data.get("period_ended"),
                "period_type": "quarter",
                "quarter": extraction_data.get("quarter"),
                "financial_year": extraction_data.get("financial_year"),
                "eps_basic": extraction_data.get("eps_basic_standalone"),
                "eps_diluted": extraction_data.get("eps_diluted_standalone"),
            }]
            consolidated_periods = [{
                "column_header": extraction_data.get("period_ended"),
                "period_type": "quarter",
                "quarter": extraction_data.get("quarter"),
                "financial_year": extraction_data.get("financial_year"),
                "eps_basic": extraction_data.get("eps_basic_consolidated"),
                "eps_diluted": extraction_data.get("eps_diluted_consolidated"),
            }]
        else:
            raise ValueError(f"No periods extracted for {stock_symbol}")

    # Coerce AI-supplied numerics (handles "(0.17)" -> -0.17, "1,234.56" -> 1234.56,
    # "NA"/"-"/"NM" -> None) before any FY-EPS math or DB INSERT.
    _normalize_periods(standalone_periods)
    _normalize_periods(consolidated_periods)

    fy_eps = _compute_all_fy_eps({
        "standalone_periods": standalone_periods,
        "consolidated_periods": consolidated_periods,
    })
    fy_basic_s = fy_eps["fy_eps_basic_standalone"].get("value")
    fy_diluted_s = fy_eps["fy_eps_diluted_standalone"].get("value")
    fy_basic_c = fy_eps["fy_eps_basic_consolidated"].get("value")
    fy_diluted_c = fy_eps["fy_eps_diluted_consolidated"].get("value")
    fy_formula_s = fy_eps["fy_eps_basic_standalone"].get("formula")
    fy_formula_c = fy_eps["fy_eps_basic_consolidated"].get("formula")

    period_map: Dict = {}
    cum_map_s: Dict = {}
    cum_map_c: Dict = {}

    def _add(periods, dest_key, cum_dest):
        for p in periods:
            q = p.get("quarter")
            fy = p.get("financial_year")
            pt = p.get("period_type", "quarter")
            if not q or not fy:
                continue
            data = {k: v for k, v in p.items()
                    if k not in ("column_header", "period_type", "quarter", "financial_year")}
            if pt in ("six_month", "nine_month"):
                cum_dest[(q, fy)] = data
            else:
                key = (q, fy)
                if key not in period_map:
                    period_map[key] = {
                        "period_ended": p.get("column_header"),
                        "standalone": None, "consolidated": None,
                    }
                period_map[key][dest_key] = data

    _add(standalone_periods, "standalone", cum_map_s)
    _add(consolidated_periods, "consolidated", cum_map_c)

    for (q, fy), cum in cum_map_s.items():
        if (q, fy) in period_map and period_map[(q, fy)]["standalone"]:
            period_map[(q, fy)]["standalone"]["cumulative_eps_basic"] = _to_float(cum.get("eps_basic"))
            period_map[(q, fy)]["standalone"]["cumulative_eps_diluted"] = _to_float(cum.get("eps_diluted"))
    for (q, fy), cum in cum_map_c.items():
        if (q, fy) in period_map and period_map[(q, fy)]["consolidated"]:
            period_map[(q, fy)]["consolidated"]["cumulative_eps_basic"] = _to_float(cum.get("eps_basic"))
            period_map[(q, fy)]["consolidated"]["cumulative_eps_diluted"] = _to_float(cum.get("eps_diluted"))

    if not period_map:
        raise ValueError(f"No mappable (quarter, fy) entries for {stock_symbol}")

    now = datetime.now(timezone.utc)
    ann_dt = _parse_announcement_date(announcement_date) or now
    raw_ai_str = json.dumps(extraction_data)

    inserted_ids: List[int] = []
    first_row = True

    async with get_db_session() as db:
        for (quarter, fy), data in period_map.items():
            sd = data["standalone"]
            cd = data["consolidated"]
            params = {
                "sym": stock_symbol,
                "cn": ai_company_name,
                "q": quarter,
                "fy": fy,
                "pe": data["period_ended"],
                "ebs": (sd or {}).get("eps_basic"),
                "eds": (sd or {}).get("eps_diluted"),
                "ebc": (cd or {}).get("eps_basic"),
                "edc": (cd or {}).get("eps_diluted"),
                "fy_eb_s": fy_basic_s,
                "fy_ed_s": fy_diluted_s,
                "fy_eb_c": fy_basic_c,
                "fy_ed_c": fy_diluted_c,
                "fy_form_s": fy_formula_s,
                "fy_form_c": fy_formula_c,
                "cum_eb_s": (sd or {}).get("cumulative_eps_basic"),
                "cum_ed_s": (sd or {}).get("cumulative_eps_diluted"),
                "cum_eb_c": (cd or {}).get("cumulative_eps_basic"),
                "cum_ed_c": (cd or {}).get("cumulative_eps_diluted"),
                "sd": json.dumps(sd) if sd else None,
                "cd": json.dumps(cd) if cd else None,
                "rar": raw_ai_str if first_row else None,
                "pdf": pdf_url,
                "ex": exchange,
                "units": units,
                "ann_date": ann_dt,
                "now": now,
            }
            result = await db.execute(_QR_UPSERT_SQL, params)
            row_id = result.scalar()
            if row_id is not None:
                inserted_ids.append(row_id)
            first_row = False

        # Cleanup: any leftover 'pending' placeholder rows for this same PDF
        # whose (quarter, fy, ann_date) didn't match what the AI produced are
        # now orphans — drop them so PE Pending doesn't show stuck QUEUED rows.
        if inserted_ids and pdf_url:
            await db.execute(text("""
                DELETE FROM quarterly_results
                WHERE source_pdf_url = :pdf
                  AND stock_symbol = :sym
                  AND extraction_status = 'pending'
                  AND id <> ALL(:keep)
            """), {"pdf": pdf_url, "sym": stock_symbol, "keep": inserted_ids})

        await db.commit()

    logger.info(
        f"Saved {len(inserted_ids)} period rows for {stock_symbol} "
        f"(FY-EPS basic_s={fy_basic_s} diluted_c={fy_diluted_c})"
    )

    await invalidate_pe_analysis()
    return inserted_ids


async def fetch_and_save_cmp(stock_symbol: str, exchange: str = "NSE") -> Optional[float]:
    """
    Fetch current market price for stock and update quarterly_results.
    Calculates PE ratio (CMP / FY_EPS).
    """
    from .quote_fetcher import get_single_quote

    cmp = await get_single_quote(stock_symbol, exchange)
    if cmp is None:
        return None

    now = datetime.now(timezone.utc)

    async with get_db_session() as db:
        # Update the latest result row for this stock with CMP + PE
        await db.execute(text("""
            UPDATE quarterly_results
            SET cmp = :cmp, cmp_updated_at = :now,
                pe = CASE
                    WHEN COALESCE(fy_eps_diluted_consolidated, fy_eps_diluted_standalone, fy_eps_basic_consolidated, fy_eps_basic_standalone, 0) > 0
                    THEN :cmp / COALESCE(fy_eps_diluted_consolidated, fy_eps_diluted_standalone, fy_eps_basic_consolidated, fy_eps_basic_standalone)
                    ELSE NULL
                END
            WHERE stock_symbol = :sym
            AND id = (SELECT id FROM quarterly_results WHERE stock_symbol = :sym ORDER BY created_at DESC LIMIT 1)
        """), {"cmp": cmp, "now": now, "sym": stock_symbol})
        await db.commit()

    return cmp


async def run_ai_stock_analysis(stock_symbol: str, analysis_type: str = "valuation") -> Dict:
    """
    Run AI-powered stock valuation/recommendation analysis.
    Uses historical quarterly data + current PE to generate insights.
    """
    async with get_db_session() as db:
        rows = await db.execute(text("""
            SELECT stock_symbol, quarter, financial_year, 
                   eps_diluted_consolidated, eps_diluted_standalone,
                   cmp, pe, valuation
            FROM quarterly_results
            WHERE stock_symbol = :sym AND extraction_status = 'completed'
            ORDER BY financial_year DESC, quarter DESC
            LIMIT 8
        """), {"sym": stock_symbol})
        history = [dict(r._mapping) for r in rows.fetchall()]

    if not history:
        return {"error": f"No data found for {stock_symbol}"}

    # Format for AI analysis
    import json
    prompt = f"""Analyze {stock_symbol} based on quarterly results:
{json.dumps(history, indent=2, default=str)}

Provide: valuation (CHEAP / UNDER_VALUED / INLINE / FAIRLY_VALUED / EXPENSIVE / IGNORE),
recommendation (BUY/SELL/HOLD), target_price, reasoning (2-3 sentences).
Use UNDER_VALUED only if conviction is high; use IGNORE for shell companies / illiquid /
data-quality issues; use INLINE for in-line-with-market PE; use FAIRLY_VALUED for slightly
above-cheap to slightly-below-expensive range."""

    try:
        client = _get_openai_client()
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        result = json.loads(data["choices"][0]["message"]["content"])

        if result.get("valuation") or result.get("recommendation"):
            async with get_db_session() as db:
                await db.execute(text("""
                    UPDATE quarterly_results
                    SET valuation = COALESCE(:val, valuation),
                        recommendation = COALESCE(:rec, recommendation),
                        target_price = COALESCE(:tp, target_price),
                        updated_at = NOW()
                    WHERE stock_symbol = :sym
                    AND id = (SELECT id FROM quarterly_results WHERE stock_symbol = :sym ORDER BY created_at DESC LIMIT 1)
                """), {
                    "val": result.get("valuation"),
                    "rec": result.get("recommendation"),
                    "tp": result.get("target_price"),
                    "sym": stock_symbol,
                })
                await db.commit()

        return result
    except Exception as e:
        logger.error(f"AI analysis failed for {stock_symbol}: {e}")
        return {"error": str(e)}
