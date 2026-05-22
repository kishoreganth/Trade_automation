"""
Concall (conference call) transcript extraction service.
Extracts actionable investment insights from earnings call PDFs using text extraction + AI.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import fitz
import httpx
from sqlalchemy import text

from ..config import get_settings
from ..database import get_db_session
from ..cache_keys import invalidate_messages
from .ocr_extractor import _get_openai_client, download_pdf_bytes

logger = logging.getLogger(__name__)
settings = get_settings()

_IST = timezone(timedelta(hours=5, minutes=30))

_CONCALL_KEYWORDS = (
    "conference call", "earnings call", "concall", "q&a",
    "question and answer", "moderator", "analyst", "investor",
    "opening remarks", "management", "participants",
)
_MIN_CONCALL_KEYWORDS = 2


def _is_concall_transcript(text_content: str) -> bool:
    """Check if extracted text is actually a concall transcript."""
    lower = text_content.lower()
    hits = sum(1 for kw in _CONCALL_KEYWORDS if kw in lower)
    return hits >= _MIN_CONCALL_KEYWORDS


async def extract_text_from_pdf(pdf_url: str) -> Optional[str]:
    """Download PDF and extract full text content using PyMuPDF."""
    pdf_bytes = await download_pdf_bytes(pdf_url)
    if pdf_bytes is None:
        return None

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        full_text = []
        for page_idx in range(doc.page_count):
            page_text = doc.load_page(page_idx).get_text("text")
            if page_text.strip():
                full_text.append(page_text)
        doc.close()

        combined = "\n\n".join(full_text)
        if not combined.strip():
            logger.warning(f"PDF has no text layer: {pdf_url}")
            return None

        return combined
    except Exception as e:
        logger.error(f"PDF text extraction failed ({pdf_url}): {e}")
        return None


def _truncate_transcript(text_content: str, max_chars: int = 60000) -> str:
    """Truncate transcript to fit within token limits while preserving structure.
    ~60k chars ≈ ~15k tokens for GPT-4.1-mini input."""
    if len(text_content) <= max_chars:
        return text_content

    # Keep intro (management remarks) + Q&A section
    # Concalls typically: cover letter -> opening remarks -> financials -> Q&A
    qa_markers = ["question and answer", "q&a session", "we will now begin",
                  "first question", "open the floor"]
    lower = text_content.lower()

    qa_start = -1
    for marker in qa_markers:
        idx = lower.find(marker)
        if idx > 0:
            qa_start = idx
            break

    if qa_start > 0:
        intro = text_content[:min(qa_start, max_chars // 3)]
        remaining = max_chars - len(intro) - 100
        qa_section = text_content[qa_start:qa_start + remaining]
        return intro + "\n\n[...transcript truncated...]\n\n" + qa_section

    return text_content[:max_chars] + "\n\n[...transcript truncated...]"


_CONCALL_EXTRACTION_PROMPT = """You are analyzing an Indian company's quarterly earnings conference call transcript.
Extract ALL actionable investment insights in structured JSON format.

IMPORTANT RULES:
- Extract ONLY information explicitly stated or directly implied in the transcript.
- Use null for any metric NOT mentioned or discussed.
- For percentage values, return the number only (e.g., 12.4 not "12.4%").
- For monetary values, convert to INR crores. State the unit in revenue_unit.
- growth_drivers, key_risks, new_products, margin_levers should be JSON arrays of short strings.
- key_takeaways should be 5-7 bullet points that an investor would find most actionable.
- management_outlook: one of "bullish", "neutral", "cautious", "mixed"
- next_quarter_outlook: one of "positive", "neutral", "negative"
- management_confidence: integer 1-5 (1=very low confidence/defensive, 5=very confident/aggressive targets)

Return ONLY raw JSON. No markdown, no code blocks.

{
    "company_name": "string",
    "quarter": "Q1|Q2|Q3|Q4",
    "financial_year": "YYYY-YY format e.g. 2025-26",

    "quantitative": {
        "revenue_mentioned": number_or_null,
        "revenue_unit": "crores|million|lakhs",
        "ebitda_margin_pct": number_or_null,
        "pat_margin_pct": number_or_null,
        "capacity_utilization_pct": number_or_null,
        "capex_current_year": number_or_null,
        "capex_planned_next": number_or_null,
        "revenue_guidance_low": number_or_null,
        "revenue_guidance_high": number_or_null,
        "export_share_pct": number_or_null,
        "market_share_pct": number_or_null,
        "technical_fee_pct": number_or_null,
        "industry_volume": number_or_null,
        "yoy_revenue_growth_pct": number_or_null,
        "qoq_revenue_growth_pct": number_or_null
    },

    "qualitative": {
        "management_outlook": "bullish|neutral|cautious|mixed",
        "next_quarter_outlook": "positive|neutral|negative",
        "management_confidence": 1-5,
        "growth_drivers": ["driver1", "driver2", ...],
        "key_risks": ["risk1", "risk2", ...],
        "new_products": ["product1", "product2", ...],
        "expansion_plans": "brief summary or null",
        "margin_levers": ["lever1", "lever2", ...],
        "competitive_position": "brief summary or null",
        "customer_updates": "brief summary or null",
        "sector_trends": "brief summary or null"
    },

    "summaries": {
        "executive_summary": "2-3 sentence summary of the call's key message",
        "investment_thesis": "1-2 sentence thesis: why buy or avoid this stock based on this call",
        "key_takeaways": ["takeaway1", "takeaway2", ..., "takeaway7"]
    }
}"""


async def extract_concall_insights_ai(
    transcript: str,
    stock_symbol: str,
    company_name: str,
) -> Optional[Dict]:
    """Send concall transcript to OpenAI for structured insight extraction."""
    if not settings.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not configured")
        return None

    if not transcript or len(transcript) < 500:
        logger.warning(f"Transcript too short for {stock_symbol}: {len(transcript or '')} chars")
        return None

    truncated = _truncate_transcript(transcript)

    messages = [
        {"role": "system", "content": _CONCALL_EXTRACTION_PROMPT},
        {"role": "user", "content": f"Company: {company_name} ({stock_symbol})\n\nTRANSCRIPT:\n{truncated}"},
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
                "max_tokens": 4000,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        logger.info(
            f"Concall AI for {stock_symbol}: prompt_tokens={usage.get('prompt_tokens')}, "
            f"completion_tokens={usage.get('completion_tokens')}"
        )
        ai_content = data["choices"][0]["message"].get("content")
        if not ai_content:
            logger.error(f"OpenAI returned empty content for concall {stock_symbol}")
            return None
        return json.loads(ai_content)
    except Exception as e:
        logger.error(f"Concall AI extraction failed for {stock_symbol}: {e}")
        return None


def _derive_quarter_fy(transcript: str) -> tuple[Optional[str], Optional[str]]:
    """Try to derive quarter and FY from transcript text."""
    lower = transcript[:3000].lower()

    # Patterns like "Q4 FY '26", "Q4 FY26", "Q4 FY 2026", "4QFY26"
    patterns = [
        r"(\d)q\s*fy\s*['\u2018\u2019]?(\d{2,4})",
        r"q(\d)\s*fy\s*['\u2018\u2019]?(\d{2,4})",
        r"q(\d)\s+fy\s*(\d{2,4})",
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            q_num = m.group(1)
            fy_raw = m.group(2)
            quarter = f"Q{q_num}"
            if len(fy_raw) == 2:
                end_yr = 2000 + int(fy_raw)
            else:
                end_yr = int(fy_raw)
            financial_year = f"{end_yr - 1}-{str(end_yr)[-2:]}"
            return quarter, financial_year

    return None, None


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


async def save_concall_insight(
    stock_symbol: str,
    company_name: str,
    exchange: str,
    pdf_url: str,
    message_id: Optional[int],
    announcement_date: Optional[datetime],
    extraction_data: Dict,
    transcript_length: int,
) -> Optional[int]:
    """Save extracted concall insights to the database."""
    if not extraction_data:
        raise ValueError(f"Empty extraction data for {stock_symbol}")

    ai_company = extraction_data.get("company_name") or company_name
    quarter = extraction_data.get("quarter")
    financial_year = extraction_data.get("financial_year")

    if financial_year:
        financial_year = _normalize_fy(financial_year)

    if not quarter or not financial_year:
        raise ValueError(f"Could not determine quarter/FY for {stock_symbol}")

    quant = extraction_data.get("quantitative", {}) or {}
    qual = extraction_data.get("qualitative", {}) or {}
    summaries = extraction_data.get("summaries", {}) or {}

    now = datetime.now(timezone.utc)

    params = {
        "sym": stock_symbol,
        "cn": ai_company,
        "q": quarter,
        "fy": financial_year,
        "pdf": pdf_url,
        "msg_id": message_id,
        "ex": exchange,
        # Quantitative
        "rev": quant.get("revenue_mentioned"),
        "rev_unit": quant.get("revenue_unit"),
        "ebitda": quant.get("ebitda_margin_pct"),
        "pat": quant.get("pat_margin_pct"),
        "cap_util": quant.get("capacity_utilization_pct"),
        "capex_curr": quant.get("capex_current_year"),
        "capex_next": quant.get("capex_planned_next"),
        "rev_low": quant.get("revenue_guidance_low"),
        "rev_high": quant.get("revenue_guidance_high"),
        "export": quant.get("export_share_pct"),
        "mkt_share": quant.get("market_share_pct"),
        "tech_fee": quant.get("technical_fee_pct"),
        "ind_vol": quant.get("industry_volume"),
        "yoy": quant.get("yoy_revenue_growth_pct"),
        "qoq": quant.get("qoq_revenue_growth_pct"),
        # Qualitative
        "outlook": qual.get("management_outlook"),
        "nq_outlook": qual.get("next_quarter_outlook"),
        "confidence": qual.get("management_confidence"),
        "drivers": json.dumps(qual.get("growth_drivers")) if qual.get("growth_drivers") else None,
        "risks": json.dumps(qual.get("key_risks")) if qual.get("key_risks") else None,
        "products": json.dumps(qual.get("new_products")) if qual.get("new_products") else None,
        "expansion": qual.get("expansion_plans"),
        "margins": json.dumps(qual.get("margin_levers")) if qual.get("margin_levers") else None,
        "competitive": qual.get("competitive_position"),
        "customers": qual.get("customer_updates"),
        "sector": qual.get("sector_trends"),
        # Summaries
        "exec_summary": summaries.get("executive_summary"),
        "thesis": summaries.get("investment_thesis"),
        "takeaways": json.dumps(summaries.get("key_takeaways")) if summaries.get("key_takeaways") else None,
        # Metadata
        "raw": json.dumps(extraction_data),
        "tlen": transcript_length,
        "ann_date": announcement_date,
        "now": now,
    }

    sql = text("""
        INSERT INTO concall_insights (
            stock_symbol, company_name, quarter, financial_year,
            source_pdf_url, source_message_id, exchange,
            revenue_mentioned, revenue_unit, ebitda_margin_pct, pat_margin_pct,
            capacity_utilization_pct, capex_current_year, capex_planned_next,
            revenue_guidance_low, revenue_guidance_high, export_share_pct,
            market_share_pct, technical_fee_pct, industry_volume,
            yoy_revenue_growth_pct, qoq_revenue_growth_pct,
            management_outlook, next_quarter_outlook, management_confidence,
            growth_drivers, key_risks, new_products, expansion_plans,
            margin_levers, competitive_position, customer_updates, sector_trends,
            executive_summary, investment_thesis, key_takeaways,
            raw_ai_response, transcript_length,
            extraction_status, announcement_date, created_at, updated_at
        ) VALUES (
            :sym, :cn, :q, :fy,
            :pdf, :msg_id, :ex,
            :rev, :rev_unit, :ebitda, :pat,
            :cap_util, :capex_curr, :capex_next,
            :rev_low, :rev_high, :export,
            :mkt_share, :tech_fee, :ind_vol,
            :yoy, :qoq,
            :outlook, :nq_outlook, :confidence,
            :drivers, :risks, :products, :expansion,
            :margins, :competitive, :customers, :sector,
            :exec_summary, :thesis, :takeaways,
            :raw, :tlen,
            'completed', :ann_date, :now, :now
        )
        ON CONFLICT (stock_symbol, quarter, financial_year, source_pdf_url)
        DO UPDATE SET
            company_name = COALESCE(EXCLUDED.company_name, concall_insights.company_name),
            revenue_mentioned = COALESCE(EXCLUDED.revenue_mentioned, concall_insights.revenue_mentioned),
            revenue_unit = COALESCE(EXCLUDED.revenue_unit, concall_insights.revenue_unit),
            ebitda_margin_pct = COALESCE(EXCLUDED.ebitda_margin_pct, concall_insights.ebitda_margin_pct),
            pat_margin_pct = COALESCE(EXCLUDED.pat_margin_pct, concall_insights.pat_margin_pct),
            capacity_utilization_pct = COALESCE(EXCLUDED.capacity_utilization_pct, concall_insights.capacity_utilization_pct),
            capex_current_year = COALESCE(EXCLUDED.capex_current_year, concall_insights.capex_current_year),
            capex_planned_next = COALESCE(EXCLUDED.capex_planned_next, concall_insights.capex_planned_next),
            revenue_guidance_low = COALESCE(EXCLUDED.revenue_guidance_low, concall_insights.revenue_guidance_low),
            revenue_guidance_high = COALESCE(EXCLUDED.revenue_guidance_high, concall_insights.revenue_guidance_high),
            export_share_pct = COALESCE(EXCLUDED.export_share_pct, concall_insights.export_share_pct),
            market_share_pct = COALESCE(EXCLUDED.market_share_pct, concall_insights.market_share_pct),
            technical_fee_pct = COALESCE(EXCLUDED.technical_fee_pct, concall_insights.technical_fee_pct),
            industry_volume = COALESCE(EXCLUDED.industry_volume, concall_insights.industry_volume),
            yoy_revenue_growth_pct = COALESCE(EXCLUDED.yoy_revenue_growth_pct, concall_insights.yoy_revenue_growth_pct),
            qoq_revenue_growth_pct = COALESCE(EXCLUDED.qoq_revenue_growth_pct, concall_insights.qoq_revenue_growth_pct),
            management_outlook = COALESCE(EXCLUDED.management_outlook, concall_insights.management_outlook),
            next_quarter_outlook = COALESCE(EXCLUDED.next_quarter_outlook, concall_insights.next_quarter_outlook),
            management_confidence = COALESCE(EXCLUDED.management_confidence, concall_insights.management_confidence),
            growth_drivers = COALESCE(EXCLUDED.growth_drivers, concall_insights.growth_drivers),
            key_risks = COALESCE(EXCLUDED.key_risks, concall_insights.key_risks),
            new_products = COALESCE(EXCLUDED.new_products, concall_insights.new_products),
            expansion_plans = COALESCE(EXCLUDED.expansion_plans, concall_insights.expansion_plans),
            margin_levers = COALESCE(EXCLUDED.margin_levers, concall_insights.margin_levers),
            competitive_position = COALESCE(EXCLUDED.competitive_position, concall_insights.competitive_position),
            customer_updates = COALESCE(EXCLUDED.customer_updates, concall_insights.customer_updates),
            sector_trends = COALESCE(EXCLUDED.sector_trends, concall_insights.sector_trends),
            executive_summary = COALESCE(EXCLUDED.executive_summary, concall_insights.executive_summary),
            investment_thesis = COALESCE(EXCLUDED.investment_thesis, concall_insights.investment_thesis),
            key_takeaways = COALESCE(EXCLUDED.key_takeaways, concall_insights.key_takeaways),
            raw_ai_response = COALESCE(EXCLUDED.raw_ai_response, concall_insights.raw_ai_response),
            transcript_length = COALESCE(EXCLUDED.transcript_length, concall_insights.transcript_length),
            extraction_status = 'completed',
            extraction_error = NULL,
            updated_at = :now
        RETURNING id
    """)

    async with get_db_session() as db:
        result = await db.execute(sql, params)
        row_id = result.scalar()
        await db.commit()

    logger.info(f"Saved concall insight for {stock_symbol} {quarter} {financial_year} (id={row_id})")
    return row_id
