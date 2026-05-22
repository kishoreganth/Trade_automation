"""
Announcement insight extraction service.
Extracts comprehensive financial data from Investor Presentations and Monthly Business Updates.
Supports two modes: Vision (image-based) and Text (text-based PDFs).
"""

import base64
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import fitz
from sqlalchemy import text

from ..config import get_settings
from ..database import get_db_session
from .ocr_extractor import _get_openai_client, download_pdf_bytes, _render_pages_to_png

logger = logging.getLogger(__name__)
settings = get_settings()

_IST = timezone(timedelta(hours=5, minutes=30))

_MAX_VISION_PAGES = 15
_MAX_TEXT_CHARS = 60000


def _detect_extraction_mode(pdf_bytes: bytes) -> tuple[str, int]:
    """Detect whether to use vision or text mode.
    Returns (mode, total_pages). Vision for image-heavy PDFs, text for text-rich."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = doc.page_count
    text_pages = 0
    total_text_len = 0

    for idx in range(min(total, 10)):
        page_text = doc.load_page(idx).get_text("text")
        if len(page_text.strip()) > 100:
            text_pages += 1
            total_text_len += len(page_text)

    doc.close()

    # If average text per page is low, it's likely image-heavy (investor pres with charts)
    avg_text = total_text_len / max(text_pages, 1)
    if text_pages < 3 or avg_text < 300:
        return "vision", total

    return "text", total


def _extract_full_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF using PyMuPDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for idx in range(doc.page_count):
        t = doc.load_page(idx).get_text("text")
        if t.strip():
            pages.append(t)
    doc.close()
    combined = "\n\n".join(pages)
    if len(combined) > _MAX_TEXT_CHARS:
        combined = combined[:_MAX_TEXT_CHARS] + "\n\n[...truncated...]"
    return combined


def _select_pages_for_vision(pdf_bytes: bytes) -> List[int]:
    """Select most relevant pages for vision extraction (skip cover, legal pages)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = doc.page_count
    # Skip first page (usually cover) and last 1-2 (disclaimers)
    start = 1 if total > 3 else 0
    end = min(total, _MAX_VISION_PAGES + start)
    if total > _MAX_VISION_PAGES + 2:
        end = total - 1  # skip last disclaimer page
        end = min(end, start + _MAX_VISION_PAGES)
    pages = list(range(start, end))
    doc.close()
    return pages


_ANNOUNCEMENT_EXTRACTION_PROMPT = """You are a senior equity research analyst extracting comprehensive investment data from an Indian company's Investor Presentation or Monthly Business Update PDF.

Extract ALL available financial metrics, segment data, forward-looking statements, and qualitative signals. This data will be used to make investment decisions for the next quarter.

RULES:
- Extract ONLY information explicitly stated or directly implied in the document.
- Use null for any metric NOT present in the document.
- For percentage values, return the number only (e.g., 12.4 not "12.4%").
- For monetary values in INR, normalize to crores. State the unit in revenue_unit.
- Arrays should be JSON arrays of objects or strings as specified.
- management_outlook: one of "bullish", "neutral", "cautious", "mixed"
- next_quarter_outlook: one of "positive", "neutral", "negative"
- margin_signal: one of "expanding", "stable", "compressing"
- management_confidence: integer 1-5

Return ONLY raw JSON. No markdown, no code blocks.

{
    "company_name": "string",
    "quarter": "Q1|Q2|Q3|Q4",
    "financial_year": "YYYY-YY format e.g. 2025-26",

    "financials": {
        "revenue": number_or_null,
        "revenue_unit": "crores|million|lakhs",
        "ebitda": number_or_null,
        "ebitda_margin_pct": number_or_null,
        "pat": number_or_null,
        "pat_margin_pct": number_or_null,
        "eps_basic": number_or_null,
        "eps_diluted": number_or_null,
        "roce_pct": number_or_null,
        "roe_pct": number_or_null,
        "debt_to_equity": number_or_null,
        "working_capital_days": number_or_null,
        "free_cash_flow": number_or_null,
        "order_book_value": number_or_null,
        "dividend_per_share": number_or_null,
        "dividend_payout_ratio": number_or_null,
        "capex_current_year": number_or_null,
        "capex_planned_next": number_or_null,
        "revenue_guidance_low": number_or_null,
        "revenue_guidance_high": number_or_null,
        "export_share_pct": number_or_null,
        "domestic_share_pct": number_or_null,
        "yoy_revenue_growth_pct": number_or_null,
        "qoq_revenue_growth_pct": number_or_null,
        "capacity_utilization_pct": number_or_null
    },

    "segments": {
        "segment_revenue": [{"name": "segment_name", "revenue": number, "margin_pct": number_or_null}],
        "geography_split": [{"region": "name", "pct": number}],
        "product_mix": [{"product": "name", "pct": number}],
        "customer_concentration": "brief description or null"
    },

    "forward_looking": {
        "revenue_growth_guidance": "brief description or null",
        "margin_signal": "expanding|stable|compressing|null",
        "industry_tailwinds": ["tailwind1", "tailwind2"],
        "industry_headwinds": ["headwind1", "headwind2"],
        "management_priorities": ["priority1", "priority2", "priority3"],
        "capex_timeline": "brief description or null",
        "new_market_entries": ["market1", "market2"],
        "hiring_plans": "brief description or null"
    },

    "qualitative": {
        "management_outlook": "bullish|neutral|cautious|mixed",
        "management_confidence": 1-5,
        "competitive_moat": "brief description or null",
        "esg_highlights": "brief description or null",
        "key_risks": ["risk1", "risk2", "risk3"],
        "growth_drivers": ["driver1", "driver2", "driver3"],
        "next_quarter_outlook": "positive|neutral|negative"
    },

    "summaries": {
        "executive_summary": "2-3 sentence summary of the document's key message",
        "investment_thesis": "1-2 sentence thesis: why buy or avoid this stock",
        "key_takeaways": ["takeaway1", "takeaway2", ..., "takeaway7"],
        "next_quarter_prediction": "What to watch for next quarter (1-2 sentences)",
        "bull_case": "1 sentence best-case scenario",
        "bear_case": "1 sentence worst-case scenario"
    }
}"""


async def extract_announcement_vision(
    pdf_bytes: bytes,
    stock_symbol: str,
    company_name: str,
    page_indices: List[int],
) -> Optional[Dict]:
    """Extract insights using Vision API (image-based)."""
    if not settings.OPENAI_API_KEY:
        return None

    images = _render_pages_to_png(pdf_bytes, page_indices, zoom=1.5)
    if not images:
        return None

    content = [{"type": "text", "text": _ANNOUNCEMENT_EXTRACTION_PROMPT}]
    content.append({"type": "text", "text": f"\nCompany: {company_name} ({stock_symbol})\n"})
    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

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
                "max_tokens": 6000,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        logger.info(
            f"Announcement Vision AI for {stock_symbol}: prompt_tokens={usage.get('prompt_tokens')}, "
            f"completion_tokens={usage.get('completion_tokens')}, images={len(images)}"
        )
        ai_content = data["choices"][0]["message"].get("content")
        if not ai_content:
            return None
        return json.loads(ai_content)
    except Exception as e:
        logger.error(f"Announcement Vision extraction failed for {stock_symbol}: {e}")
        return None


async def extract_announcement_text(
    text_content: str,
    stock_symbol: str,
    company_name: str,
) -> Optional[Dict]:
    """Extract insights using text mode."""
    if not settings.OPENAI_API_KEY:
        return None

    if not text_content or len(text_content) < 200:
        return None

    messages = [
        {"role": "system", "content": _ANNOUNCEMENT_EXTRACTION_PROMPT},
        {"role": "user", "content": f"Company: {company_name} ({stock_symbol})\n\nDOCUMENT:\n{text_content}"},
    ]

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
                "messages": messages,
                "temperature": 0,
                "max_tokens": 6000,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        logger.info(
            f"Announcement Text AI for {stock_symbol}: prompt_tokens={usage.get('prompt_tokens')}, "
            f"completion_tokens={usage.get('completion_tokens')}"
        )
        ai_content = data["choices"][0]["message"].get("content")
        if not ai_content:
            return None
        return json.loads(ai_content)
    except Exception as e:
        logger.error(f"Announcement Text extraction failed for {stock_symbol}: {e}")
        return None


def _normalize_fy(fy: str) -> str:
    """Normalize financial_year to 'YYYY-YY' format."""
    if not fy:
        return fy
    fy = fy.strip()
    m = re.match(r"^(\d{4})$", fy)
    if m:
        end_yr = int(m.group(1))
        return f"{end_yr - 1}-{str(end_yr)[-2:]}"
    m = re.match(r"^FY(\d{2})$", fy, re.IGNORECASE)
    if m:
        end_yr = 2000 + int(m.group(1))
        return f"{end_yr - 1}-{str(end_yr)[-2:]}"
    m = re.match(r"^FY(\d{4})$", fy, re.IGNORECASE)
    if m:
        end_yr = int(m.group(1))
        return f"{end_yr - 1}-{str(end_yr)[-2:]}"
    return fy


def _derive_quarter_fy_from_date(ann_date: Optional[datetime]) -> tuple[str, str]:
    """Derive quarter and FY from announcement date when AI can't determine it."""
    if ann_date is None:
        ann_date = datetime.now(_IST)
    y, m = ann_date.year, ann_date.month
    if 4 <= m <= 6:
        return "Q4", f"{y - 1}-{str(y)[-2:]}"
    if 7 <= m <= 9:
        return "Q1", f"{y}-{str(y + 1)[-2:]}"
    if 10 <= m <= 12:
        return "Q2", f"{y}-{str(y + 1)[-2:]}"
    return "Q3", f"{y - 1}-{str(y)[-2:]}"


async def save_announcement_insight(
    stock_symbol: str,
    company_name: str,
    exchange: str,
    pdf_url: str,
    announcement_type: str,
    message_id: Optional[int],
    announcement_date: Optional[datetime],
    extraction_data: Dict,
    extraction_mode: str,
    pages_processed: int,
) -> Optional[int]:
    """Save extracted announcement insights to the database."""
    if not extraction_data:
        raise ValueError(f"Empty extraction data for {stock_symbol}")

    ai_company = extraction_data.get("company_name") or company_name
    quarter = extraction_data.get("quarter")
    financial_year = extraction_data.get("financial_year")

    if financial_year:
        financial_year = _normalize_fy(financial_year)

    if not quarter or not financial_year:
        quarter, financial_year = _derive_quarter_fy_from_date(announcement_date)

    fin = extraction_data.get("financials", {}) or {}
    seg = extraction_data.get("segments", {}) or {}
    fwd = extraction_data.get("forward_looking", {}) or {}
    qual = extraction_data.get("qualitative", {}) or {}
    summ = extraction_data.get("summaries", {}) or {}

    now = datetime.now(timezone.utc)

    def _json_dump(val):
        if val is None:
            return None
        if isinstance(val, (list, dict)):
            return json.dumps(val)
        return str(val)

    params = {
        "sym": stock_symbol,
        "cn": ai_company,
        "q": quarter,
        "fy": financial_year,
        "ann_type": announcement_type,
        "pdf": pdf_url,
        "msg_id": message_id,
        "ex": exchange,
        # Financials
        "revenue": fin.get("revenue"),
        "rev_unit": fin.get("revenue_unit"),
        "ebitda": fin.get("ebitda"),
        "ebitda_m": fin.get("ebitda_margin_pct"),
        "pat": fin.get("pat"),
        "pat_m": fin.get("pat_margin_pct"),
        "eps_b": fin.get("eps_basic"),
        "eps_d": fin.get("eps_diluted"),
        "roce": fin.get("roce_pct"),
        "roe": fin.get("roe_pct"),
        "d2e": fin.get("debt_to_equity"),
        "wc_days": fin.get("working_capital_days"),
        "fcf": fin.get("free_cash_flow"),
        "ob": fin.get("order_book_value"),
        "dps": fin.get("dividend_per_share"),
        "dp_ratio": fin.get("dividend_payout_ratio"),
        "capex_c": fin.get("capex_current_year"),
        "capex_n": fin.get("capex_planned_next"),
        "rev_low": fin.get("revenue_guidance_low"),
        "rev_high": fin.get("revenue_guidance_high"),
        "export_pct": fin.get("export_share_pct"),
        "dom_pct": fin.get("domestic_share_pct"),
        "yoy": fin.get("yoy_revenue_growth_pct"),
        "qoq": fin.get("qoq_revenue_growth_pct"),
        "cap_util": fin.get("capacity_utilization_pct"),
        # Segments
        "seg_rev": _json_dump(seg.get("segment_revenue")),
        "geo_split": _json_dump(seg.get("geography_split")),
        "prod_mix": _json_dump(seg.get("product_mix")),
        "cust_conc": seg.get("customer_concentration"),
        # Forward-looking
        "rev_guide": fwd.get("revenue_growth_guidance"),
        "margin_sig": fwd.get("margin_signal"),
        "tailwinds": _json_dump(fwd.get("industry_tailwinds")),
        "headwinds": _json_dump(fwd.get("industry_headwinds")),
        "priorities": _json_dump(fwd.get("management_priorities")),
        "capex_tl": fwd.get("capex_timeline"),
        "new_mkts": _json_dump(fwd.get("new_market_entries")),
        "hiring": fwd.get("hiring_plans"),
        # Qualitative
        "outlook": qual.get("management_outlook"),
        "confidence": qual.get("management_confidence"),
        "moat": qual.get("competitive_moat"),
        "esg": qual.get("esg_highlights"),
        "risks": _json_dump(qual.get("key_risks")),
        "drivers": _json_dump(qual.get("growth_drivers")),
        "nq_outlook": qual.get("next_quarter_outlook"),
        # Summaries
        "exec_sum": summ.get("executive_summary"),
        "thesis": summ.get("investment_thesis"),
        "takeaways": _json_dump(summ.get("key_takeaways")),
        "nq_pred": summ.get("next_quarter_prediction"),
        "bull": summ.get("bull_case"),
        "bear": summ.get("bear_case"),
        # Metadata
        "raw": json.dumps(extraction_data),
        "mode": extraction_mode,
        "pages": pages_processed,
        "ann_date": announcement_date,
        "now": now,
    }

    sql = text("""
        INSERT INTO announcement_insights (
            stock_symbol, company_name, quarter, financial_year, announcement_type,
            source_pdf_url, source_message_id, exchange,
            revenue, revenue_unit, ebitda, ebitda_margin_pct, pat, pat_margin_pct,
            eps_basic, eps_diluted, roce_pct, roe_pct, debt_to_equity,
            working_capital_days, free_cash_flow, order_book_value,
            dividend_per_share, dividend_payout_ratio,
            capex_current_year, capex_planned_next,
            revenue_guidance_low, revenue_guidance_high,
            export_share_pct, domestic_share_pct,
            yoy_revenue_growth_pct, qoq_revenue_growth_pct, capacity_utilization_pct,
            segment_revenue, geography_split, product_mix, customer_concentration,
            revenue_growth_guidance, margin_signal,
            industry_tailwinds, industry_headwinds,
            management_priorities, capex_timeline, new_market_entries, hiring_plans,
            management_outlook, management_confidence, competitive_moat, esg_highlights,
            key_risks, growth_drivers, next_quarter_outlook,
            executive_summary, investment_thesis, key_takeaways,
            next_quarter_prediction, bull_case, bear_case,
            raw_ai_response, extraction_mode, pages_processed,
            extraction_status, announcement_date, created_at, updated_at
        ) VALUES (
            :sym, :cn, :q, :fy, :ann_type,
            :pdf, :msg_id, :ex,
            :revenue, :rev_unit, :ebitda, :ebitda_m, :pat, :pat_m,
            :eps_b, :eps_d, :roce, :roe, :d2e,
            :wc_days, :fcf, :ob,
            :dps, :dp_ratio,
            :capex_c, :capex_n,
            :rev_low, :rev_high,
            :export_pct, :dom_pct,
            :yoy, :qoq, :cap_util,
            :seg_rev, :geo_split, :prod_mix, :cust_conc,
            :rev_guide, :margin_sig,
            :tailwinds, :headwinds,
            :priorities, :capex_tl, :new_mkts, :hiring,
            :outlook, :confidence, :moat, :esg,
            :risks, :drivers, :nq_outlook,
            :exec_sum, :thesis, :takeaways,
            :nq_pred, :bull, :bear,
            :raw, :mode, :pages,
            'completed', :ann_date, :now, :now
        )
        ON CONFLICT (stock_symbol, quarter, financial_year, announcement_type, source_pdf_url)
        DO UPDATE SET
            company_name = COALESCE(EXCLUDED.company_name, announcement_insights.company_name),
            revenue = COALESCE(EXCLUDED.revenue, announcement_insights.revenue),
            ebitda_margin_pct = COALESCE(EXCLUDED.ebitda_margin_pct, announcement_insights.ebitda_margin_pct),
            pat_margin_pct = COALESCE(EXCLUDED.pat_margin_pct, announcement_insights.pat_margin_pct),
            executive_summary = COALESCE(EXCLUDED.executive_summary, announcement_insights.executive_summary),
            investment_thesis = COALESCE(EXCLUDED.investment_thesis, announcement_insights.investment_thesis),
            key_takeaways = COALESCE(EXCLUDED.key_takeaways, announcement_insights.key_takeaways),
            raw_ai_response = COALESCE(EXCLUDED.raw_ai_response, announcement_insights.raw_ai_response),
            extraction_status = 'completed',
            extraction_error = NULL,
            updated_at = :now
        RETURNING id
    """)

    async with get_db_session() as db:
        result = await db.execute(sql, params)
        row_id = result.scalar()
        await db.commit()

    logger.info(f"Saved announcement insight for {stock_symbol} {announcement_type} {quarter} {financial_year} (id={row_id})")
    return row_id
