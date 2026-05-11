"""
NSE corporate announcements fetcher.
Extracted from: nse_url_test.py (run_periodic_task_equities, CA_equities flow)
"""

import logging
from typing import List, Dict
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import text

from ..database import get_db_session
from ..cache_keys import notify_new_message, invalidate_messages, invalidate_pe_analysis
from .telegram import send_announcement_notification
from .bse_fetcher import classify_announcement

logger = logging.getLogger(__name__)

NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


async def fetch_nse_announcements(segment: str = "equities") -> List[Dict]:
    """
    Fetch latest corporate announcements from NSE API.
    Returns list of raw announcement dicts.
    """
    params = {"index": segment}
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(NSE_ANNOUNCEMENTS_URL, params=params, headers=NSE_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"NSE fetch failed ({segment}): {e}")
        return []


async def process_nse_announcements(announcements: List[Dict]) -> List[Dict]:
    """
    Process new NSE announcements:
    - Deduplicate against existing DB records
    - Save to messages table
    - Send Telegram notification
    - Return list of newly saved items (for WebSocket broadcast)
    """
    if not announcements:
        return []

    new_items = []

    async with get_db_session() as db:
        for ann in announcements:
            symbol = ann.get("symbol", "").strip()
            company_name = ann.get("sm_name", "").strip()
            description = ann.get("desc", "").strip()
            file_url = ann.get("attchmntFile", "")
            attachment_name = ann.get("attchmntText", "")

            if not symbol:
                continue

            # Dedup: check if this exact announcement already exists
            existing = await db.execute(text(
                "SELECT id FROM messages WHERE symbol = :s AND description = :d AND file_url = :f LIMIT 1"
            ), {"s": symbol, "d": description, "f": file_url})

            if existing.fetchone():
                continue

            # Save to messages table — use actual announcement time from NSE
            ann_time = _parse_nse_datetime(ann.get("an_dt") or ann.get("dt") or "")
            option = classify_announcement(description)
            result = await db.execute(text("""
                INSERT INTO messages (chat_id, message, timestamp, symbol, company_name, description, file_url, option, exchange)
                VALUES (:chat_id, :message, :ts, :symbol, :company, :desc, :file_url, :option, :exchange)
                RETURNING id
            """), {
                "chat_id": "nse_corporate",
                "message": f"{symbol}: {description}",
                "ts": ann_time,
                "symbol": symbol,
                "company": company_name,
                "desc": description,
                "file_url": file_url,
                "option": option,
                "exchange": "NSE",
            })

            msg_id = result.scalar()
            await db.commit()

            item = {
                "id": msg_id,
                "symbol": symbol,
                "company_name": company_name,
                "description": description,
                "file_url": file_url,
                "exchange": "NSE",
                "timestamp": ann_time.isoformat(),
            }
            new_items.append(item)

            await send_announcement_notification(symbol, company_name, description, "NSE")

    if new_items:
        await invalidate_messages()
        for item in new_items:
            await notify_new_message(item)

    logger.info(f"NSE: processed {len(announcements)}, new: {len(new_items)}")
    return new_items


IST = timezone(timedelta(hours=5, minutes=30))

_NSE_RESULT_KEYWORDS = (
    "financial result",
    "quarterly result",
    "audited result",
    "unaudited result",
    "outcome of board meeting",
)

NSE_PDF_BASE = "https://www.nseindia.com/corporate/content/"


async def process_nse_for_extraction(announcements: List[Dict]) -> List[Dict]:
    """
    Filter NSE announcements for quarterly results and prepare them for extraction.
    - Keyword filter on desc field
    - Excludes 'intimation' notices
    - Deduplicates against bse_announcements_log (reused for NSE)
    - Inserts pending placeholder in quarterly_results
    - Returns items ready for extraction dispatch
    """
    if not announcements:
        return []

    extraction_items: list[dict] = []

    async with get_db_session() as db:
        for ann in announcements:
            symbol = ann.get("symbol", "").strip()
            company_name = ann.get("sm_name", "").strip()
            description = ann.get("desc", "").strip()
            pdf_file = ann.get("attchmntFile", "").strip()
            an_dt = ann.get("an_dt") or ann.get("dt") or ""

            if not symbol or not pdf_file:
                continue

            desc_lower = description.lower()

            # Keyword filter: must contain at least one result keyword
            if not any(kw in desc_lower for kw in _NSE_RESULT_KEYWORDS):
                continue

            # Exclude intimation notices (advance meeting notices, no actual results)
            if "intimation" in desc_lower:
                continue

            # Build full PDF URL if it's a relative path
            if pdf_file.startswith("http"):
                pdf_url = pdf_file
            else:
                pdf_url = f"https://www.nseindia.com{pdf_file}" if pdf_file.startswith("/") else f"{NSE_PDF_BASE}{pdf_file}"

            # Dedup via bse_announcements_log (reused for NSE)
            result = await db.execute(text("""
                INSERT INTO bse_announcements_log
                (scrip_code, company_name, announcement_type, announcement_date, subject, pdf_url, exchange, processed, created_at)
                VALUES (:sc, :cn, 'quarterly_result', :ad, :sub, :pdf, 'NSE', 0, NOW())
                ON CONFLICT (scrip_code, announcement_type, pdf_url) DO NOTHING
                RETURNING id
            """), {
                "sc": symbol, "cn": company_name,
                "ad": an_dt, "sub": description, "pdf": pdf_url,
            })
            new_row = result.scalar()

            if new_row is None:
                continue  # duplicate

            # Insert pending placeholder in quarterly_results
            ann_time = _parse_nse_datetime(an_dt)
            quarter, fy = _quarter_fy_for_today()
            try:
                await db.execute(text("""
                    INSERT INTO quarterly_results
                        (stock_symbol, company_name, quarter, financial_year,
                         source_pdf_url, exchange, extraction_status,
                         announcement_date, created_at, updated_at)
                    VALUES (:sym, :cn, :q, :fy, :pdf, 'NSE', 'pending',
                            :ann, NOW(), NOW())
                    ON CONFLICT (stock_symbol, quarter, financial_year, announcement_date)
                    DO NOTHING
                """), {
                    "sym": symbol, "cn": company_name, "q": quarter, "fy": fy,
                    "pdf": pdf_url, "ann": ann_time,
                })
            except Exception as e:
                logger.warning(f"Could not insert pending placeholder for {symbol}: {e}")

            await db.commit()

            extraction_items.append({
                "symbol": symbol,
                "company_name": company_name,
                "pdf_url": pdf_url,
                "announcement_date": an_dt,
            })

    if extraction_items:
        await invalidate_pe_analysis()

    logger.info(f"NSE extraction filter: {len(announcements)} checked, {len(extraction_items)} new for extraction")
    return extraction_items


def _quarter_fy_for_today() -> tuple[str, str]:
    """Best-guess (quarter, financial_year) for current reporting cycle.
    Indian results are reported AFTER quarter end:
      Apr–Jun  -> Q4 of (y-1)-(y)
      Jul–Sep  -> Q1 of (y)-(y+1)
      Oct–Dec  -> Q2 of (y)-(y+1)
      Jan–Mar  -> Q3 of (y-1)-(y)"""
    now = datetime.now(IST)
    y, m = now.year, now.month
    if 4 <= m <= 6:
        return "Q4", f"{y - 1}-{str(y)[-2:]}"
    elif 7 <= m <= 9:
        return "Q1", f"{y}-{str(y + 1)[-2:]}"
    elif 10 <= m <= 12:
        return "Q2", f"{y}-{str(y + 1)[-2:]}"
    else:
        return "Q3", f"{y - 1}-{str(y)[-2:]}"


def _parse_nse_datetime(dt_str: str) -> datetime:
    """Parse NSE date field (IST). Returns timezone-aware datetime."""
    formats = [
        "%d-%b-%Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",
        "%d-%b-%Y",
        "%d %b %Y",
        "%Y-%m-%dT%H:%M:%S",
    ]
    if not dt_str:
        return datetime.now(IST)
    try:
        parsed = datetime.fromisoformat(dt_str.strip())
        if parsed.tzinfo is not None:
            return parsed
        return parsed.replace(tzinfo=IST)
    except (ValueError, AttributeError):
        pass
    for fmt in formats:
        try:
            parsed = datetime.strptime(dt_str.strip(), fmt)
            return parsed.replace(tzinfo=IST)
        except (ValueError, AttributeError):
            continue
    return datetime.now(IST)
