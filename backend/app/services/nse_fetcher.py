"""
NSE corporate announcements fetcher.
Uses NseIndiaApi library (nse[server]) with from_date/to_date for full-day coverage.
Supports equities and SME segments with subject-based financial result filtering.
"""

import asyncio
import logging
import tempfile
from typing import List, Dict
from datetime import datetime, timezone, timedelta

from nse import NSE
from sqlalchemy import text

from ..database import get_db_session
from ..cache_keys import notify_new_message, invalidate_messages, invalidate_pe_analysis
from .telegram import send_announcement_notification
from .bse_fetcher import classify_announcement

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_NSE_LIB_DOWNLOAD_DIR = tempfile.mkdtemp(prefix="nse_lib_")

NSE_PDF_BASE = "https://www.nseindia.com/corporate/content/"

# ---------------------------------------------------------------------------
# Subject-based financial result detection
# ---------------------------------------------------------------------------

_EXCLUDE_SUBJECTS = (
    "clarification",
    "reply to clarification",
    "reasons for delayed",
    "non-submission",
    "newspaper",
)


def _is_financial_result(ann: dict) -> bool:
    """
    Determine if an NSE announcement is a financial result filing.

    Level 1 -- direct subject match (catches all NSE dropdown subjects):
      Equities: "Audited Financial Results", "Financial Results",
                "Financial Results Updates", "Financial Results update",
                "Financial Results/Other business matters",
                "Option to submit Standalone/Consolidated Financial Results"
      SME:      "Financial Result Updates", "Financial Results Updates",
                "Financial Results/Other business matters",
                "Option to submit Standalone/Consolidated Financial Results"

    Level 2 -- board meeting fallback:
      desc == "Outcome of Board Meeting" AND attchmntText contains
      "financial result" (catches results filed under board outcomes)
    """
    desc = ann.get("desc", "").lower()
    detail = ann.get("attchmntText", "").lower()

    if any(ex in desc for ex in _EXCLUDE_SUBJECTS):
        return False

    if "intimation" in desc:
        return False

    # Newspaper publications are reprints; the actual result PDF is filed
    # separately. These PDFs contain multiple companies' data on one page
    # which causes the AI to extract the wrong company.
    if "newspaper" in detail:
        return False

    if "financial result" in desc:
        return True

    if "outcome of board meeting" in desc:
        if "financial result" in detail:
            return True

    return False


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_via_nse_lib(segment: str) -> List[Dict]:
    """
    Sync helper -- fetches ALL announcements for today using the nse library.
    Uses from_date/to_date to get the full day (not just latest 20).
    """
    today = datetime.now()
    try:
        with NSE(_NSE_LIB_DOWNLOAD_DIR, server=True) as nse:
            data = nse.announcements(
                index=segment,
                from_date=today,
                to_date=today,
            )
            rows = data if isinstance(data, list) else []
            logger.info(f"NSE lib ({segment}): fetched {len(rows)} announcements for today")
            return rows
    except Exception as e:
        logger.error(f"NSE lib fetch failed ({segment}): {type(e).__name__}: {e}")
        return []


async def fetch_nse_announcements(segment: str = "equities") -> List[Dict]:
    """
    Fetch all corporate announcements for today from NSE API.
    Returns list of raw announcement dicts.
    """
    return await asyncio.to_thread(_fetch_via_nse_lib, segment)


# ---------------------------------------------------------------------------
# Process -- feed + notifications (shared by equities and SME)
# ---------------------------------------------------------------------------

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

            existing = await db.execute(text(
                "SELECT id FROM messages WHERE symbol = :s AND description = :d AND file_url = :f LIMIT 1"
            ), {"s": symbol, "d": description, "f": file_url})

            if existing.fetchone():
                continue

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
                "option": option,
                "exchange": "NSE",
                "timestamp": ann_time.isoformat(),
            }
            new_items.append(item)

            await send_announcement_notification(symbol, company_name, description, "NSE")

    if new_items:
        await invalidate_messages()
        for item in new_items:
            await notify_new_message(item)

    concall_items = [
        i for i in new_items
        if i.get("option") in ("concall", "result_concall") and i.get("file_url")
    ]
    if concall_items:
        from worker.tasks.concall import run_concall_extraction
        for item in concall_items:
            run_concall_extraction.delay(
                stock_symbol=item["symbol"],
                pdf_url=item["file_url"],
                exchange="NSE",
                company_name=item.get("company_name", ""),
                announcement_date=item.get("timestamp"),
                message_id=item.get("id"),
            )
        logger.info(f"Dispatched {len(concall_items)} NSE concall extractions")

    ann_insight_items = [
        i for i in new_items
        if i.get("option") in ("investor_presentation", "monthly_business_update") and i.get("file_url")
    ]
    if ann_insight_items:
        from worker.tasks.announcement_insight import run_announcement_extraction
        for item in ann_insight_items:
            run_announcement_extraction.delay(
                stock_symbol=item["symbol"],
                pdf_url=item["file_url"],
                announcement_type=item["option"],
                exchange="NSE",
                company_name=item.get("company_name", ""),
                announcement_date=item.get("timestamp"),
                message_id=item.get("id"),
            )
        logger.info(f"Dispatched {len(ann_insight_items)} NSE announcement insight extractions")

    logger.info(f"NSE: processed {len(announcements)}, new: {len(new_items)}")
    return new_items


# ---------------------------------------------------------------------------
# Extraction filter -- Equities
# ---------------------------------------------------------------------------

async def process_nse_eq_for_extraction(announcements: List[Dict]) -> List[Dict]:
    """
    Filter NSE equities announcements for quarterly results and prepare for extraction.
    Uses _is_financial_result() for subject-based + board-meeting-fallback filtering.
    """
    return await _process_nse_for_extraction(announcements, segment_label="equities")


# ---------------------------------------------------------------------------
# Extraction filter -- SME
# ---------------------------------------------------------------------------

async def process_nse_sme_for_extraction(announcements: List[Dict]) -> List[Dict]:
    """
    Filter NSE SME announcements for quarterly results and prepare for extraction.
    Same filtering logic as equities via _is_financial_result().
    """
    return await _process_nse_for_extraction(announcements, segment_label="sme")


# ---------------------------------------------------------------------------
# Shared extraction filter implementation
# ---------------------------------------------------------------------------

async def _process_nse_for_extraction(
    announcements: List[Dict], segment_label: str = "equities"
) -> List[Dict]:
    """
    Shared implementation for EQ and SME extraction filtering.
    - Uses _is_financial_result() for subject + board-meeting-fallback check
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

            if not _is_financial_result(ann):
                continue

            if pdf_file.startswith("http"):
                pdf_url = pdf_file
            else:
                pdf_url = (
                    f"https://www.nseindia.com{pdf_file}"
                    if pdf_file.startswith("/")
                    else f"{NSE_PDF_BASE}{pdf_file}"
                )

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
                continue

            ann_time = _parse_nse_datetime(an_dt)
            ann_time = ann_time.replace(hour=0, minute=0, second=0, microsecond=0)
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

    logger.info(
        f"NSE extraction filter ({segment_label}): "
        f"{len(announcements)} checked, {len(extraction_items)} new for extraction"
    )
    return extraction_items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quarter_fy_for_today() -> tuple[str, str]:
    """Best-guess (quarter, financial_year) for current reporting cycle.
    Indian results are reported AFTER quarter end:
      Apr-Jun  -> Q4 of (y-1)-(y)
      Jul-Sep  -> Q1 of (y)-(y+1)
      Oct-Dec  -> Q2 of (y)-(y+1)
      Jan-Mar  -> Q3 of (y-1)-(y)"""
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
