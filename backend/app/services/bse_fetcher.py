"""
BSE corporate announcements fetcher.
Extracted from: nse_url_test.py (fetch_bse_announcements, process_bse_ca_data,
    process_bse_results_data, process_bse_board_meeting_data)
"""

import logging
from typing import List, Dict
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import text

from ..database import get_db_session
from ..cache_keys import notify_new_message, invalidate_messages, invalidate_pe_analysis
from .telegram import send_announcement_notification

logger = logging.getLogger(__name__)

BSE_API_BASE = "https://api.bseindia.com/BseIndiaAPI/api"
BSE_ANNOUNCEMENTS_URL = f"{BSE_API_BASE}/AnnSubCategoryGetData/w"
BSE_ATTACHMENT_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
}


def _build_bse_pdf_url(attachment_name: str) -> str:
    """Build full BSE PDF URL from attachment filename."""
    if not attachment_name:
        return ""
    if attachment_name.startswith("http"):
        return attachment_name
    return f"{BSE_ATTACHMENT_BASE}{attachment_name}"


# Order matters: more specific patterns first (e.g. "result_concall" before "concall")
_OPTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("result_concall", ("result and earnings call", "result & earnings call",
                         "results and concall", "results & concall",
                         "results and earnings call", "results & earnings call")),
    ("quarterly_result", ("quarterly result", "quarterly results",
                           "financial result", "financial results",
                           "audited financial result", "audited financial results",
                           "unaudited financial result", "unaudited financial results",
                           "outcome of board meeting", "board meeting outcome")),
    ("concall", ("conference call", "earnings call", "concall",
                  "investor call", "analyst call", "earnings conference")),
    ("investor_presentation", ("investor presentation", "investor pres",
                                "earnings presentation", "investor update presentation")),
    ("monthly_business_update", ("monthly business update", "business update",
                                   "monthly update", "operational update")),
    ("fund_raising", ("fund raising", "fund-raising", "fundraising",
                       "preferential issue", "preferential allotment",
                       "qualified institutional placement", "qip",
                       "rights issue", "issue of equity", "issue of debentures",
                       "issue of bonds", "issue of warrants",
                       "raising of funds", "capital raising")),
    ("board_meeting", ("intimation of board meeting", "board meeting intimation",
                        "notice of board meeting", "scheduled board meeting")),
]


def classify_announcement(subject: str) -> str:
    """
    Map BSE/NSE announcement subject to a sidebar option id.

    Returns one of: 'quarterly_result', 'concall', 'investor_presentation',
    'monthly_business_update', 'fund_raising', 'result_concall', 'board_meeting', 'all'.
    Defaults to 'all' when no rule matches.
    """
    if not subject:
        return "all"
    s = subject.lower()
    for option, keywords in _OPTION_RULES:
        for kw in keywords:
            if kw in s:
                return option
    return "all"


async def fetch_bse_announcements(category: str = "all", max_pages: int = 10) -> List[Dict]:
    """
    Fetch ALL BSE corporate announcements by category (paginated).
    category: 'all', 'result', 'board_meeting'
    """
    today = datetime.now().strftime("%Y%m%d")
    cat_code = _category_code(category)
    all_rows: List[Dict] = []

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for page_no in range(1, max_pages + 1):
                params = {
                    "pageno": str(page_no),
                    "strCat": cat_code,
                    "strPrevDate": today,
                    "strScrip": "",
                    "strSearch": "P",
                    "strToDate": today,
                    "strType": "C",
                }
                resp = await client.get(BSE_ANNOUNCEMENTS_URL, params=params, headers=BSE_HEADERS)
                resp.raise_for_status()
                data = resp.json()
                table = data.get("Table", [])
                if not table:
                    break
                all_rows.extend(table)
                if len(table) < 50:
                    break
    except Exception as e:
        logger.error(
            f"BSE fetch failed ({category}, page {page_no}): "
            f"{type(e).__name__}: {e or '<no message>'}"
        )

    return all_rows


def _category_code(category: str) -> str:
    """Map friendly category name to BSE API code."""
    mapping = {
        "all": "-1",
        "result": "Result",
        "board_meeting": "Board Meeting",
    }
    return mapping.get(category, "-1")


async def process_bse_ca_data(bse_data: List[Dict]) -> List[Dict]:
    """
    Process BSE 'all' category announcements.
    - Dedup via bse_announcements_log table
    - Save to messages table
    - Notify frontend
    """
    if not bse_data:
        return []

    new_items = []

    async with get_db_session() as db:
        for row in bse_data:
            scrip_code = str(row.get("SCRIP_CD", "")).strip()
            company_name = row.get("SLONGNAME", row.get("NEWSID", "")).strip()
            subject = row.get("NEWSSUB", "").strip()
            news_dt = row.get("NEWS_DT", "").strip()
            pdf_url = _build_bse_pdf_url(row.get("ATTACHMENTNAME", ""))

            if not scrip_code:
                continue

            # Dedup via DB (INSERT OR IGNORE on unique constraint)
            try:
                await db.execute(text("""
                    INSERT INTO bse_announcements_log
                    (scrip_code, company_name, announcement_type, announcement_date, subject, pdf_url, exchange, processed, created_at)
                    VALUES (:sc, :cn, :at, :ad, :sub, :pdf, 'BSE', 0, NOW())
                    ON CONFLICT (scrip_code, announcement_type, pdf_url) DO NOTHING
                """), {
                    "sc": scrip_code, "cn": company_name, "at": "all",
                    "ad": news_dt, "sub": subject, "pdf": pdf_url,
                })
                await db.commit()
            except Exception:
                await db.rollback()
                continue

            # Save to messages — use actual announcement time from BSE
            symbol = _scrip_to_symbol(scrip_code, company_name)
            ann_time = _parse_bse_datetime(news_dt)
            option = classify_announcement(subject)

            result = await db.execute(text("""
                INSERT INTO messages (chat_id, message, timestamp, symbol, company_name, description, file_url, option, exchange)
                VALUES (:cid, :msg, :ts, :sym, :cn, :desc, :url, :opt, 'BSE')
                RETURNING id
            """), {
                "cid": "bse_corporate", "msg": f"{symbol}: {subject}",
                "ts": ann_time, "sym": symbol, "cn": company_name,
                "desc": subject, "url": pdf_url, "opt": option,
            })
            msg_id = result.scalar()
            await db.commit()

            item = {
                "id": msg_id, "symbol": symbol, "company_name": company_name,
                "description": subject, "file_url": pdf_url, "option": option,
                "exchange": "BSE", "timestamp": ann_time.isoformat(),
            }
            new_items.append(item)

            await send_announcement_notification(symbol, company_name, subject, "BSE")

    if new_items:
        await invalidate_messages()
        for item in new_items:
            await notify_new_message(item)

    logger.info(f"BSE all: processed {len(bse_data)}, new: {len(new_items)}")
    return new_items


async def _upsert_message_for_extraction(
    db, symbol: str, company_name: str, subject: str,
    pdf_url: str, news_dt: str, default_option: str,
) -> None:
    """
    Insert (or no-op) a `messages` row for a BSE result / board-meeting item so
    sidebar feed pages (Quarterly Result / Board Meeting / Result+Concall) render it.

    Dedup is via (symbol, file_url) — same announcement won't double-insert.
    """
    option = classify_announcement(subject) or default_option
    if option == "all":
        option = default_option
    ann_time = _parse_bse_datetime(news_dt)

    existing = await db.execute(text(
        "SELECT id FROM messages WHERE symbol = :sym AND file_url = :url LIMIT 1"
    ), {"sym": symbol, "url": pdf_url})
    if existing.first() is not None:
        return

    await db.execute(text("""
        INSERT INTO messages
            (chat_id, message, timestamp, symbol, company_name, description,
             file_url, option, exchange)
        VALUES (:cid, :msg, :ts, :sym, :cn, :desc, :url, :opt, 'BSE')
    """), {
        "cid": "bse_corporate", "msg": f"{symbol}: {subject}", "ts": ann_time,
        "sym": symbol, "cn": company_name, "desc": subject,
        "url": pdf_url, "opt": option,
    })


def _quarter_fy_for_today() -> tuple[str, str]:
    """Best-guess (quarter, financial_year) when the BSE row first appears.
    Indian results are reported AFTER quarter end:
      Apr–Jun  → Q4 of (y-1)–(y)
      Jul–Sep  → Q1 of (y)–(y+1)
      Oct–Dec  → Q2 of (y)–(y+1)
      Jan–Mar  → Q3 of (y-1)–(y)"""
    now = datetime.now(IST)
    y, m = now.year, now.month
    if 4 <= m <= 6:
        return "Q4", f"{y - 1}-{str(y)[-2:]}"
    if 7 <= m <= 9:
        return "Q1", f"{y}-{str(y + 1)[-2:]}"
    if 10 <= m <= 12:
        return "Q2", f"{y}-{str(y + 1)[-2:]}"
    return "Q3", f"{y - 1}-{str(y)[-2:]}"


async def _insert_pending_qr_placeholder(
    db, symbol: str, company_name: str, pdf_url: str,
    news_dt: str, exchange: str = "BSE",
) -> None:
    """
    Insert a 'pending' quarterly_results row so the stock appears on PE Pending
    with a QUEUED badge the moment BSE returns it — well before the worker has
    actually run extraction. Uses today's quarter/FY guess; the worker overwrites
    these via UPSERT once it parses the PDF.
    """
    quarter, fy = _quarter_fy_for_today()
    ann_dt = _parse_bse_datetime(news_dt)
    try:
        await db.execute(text("""
            INSERT INTO quarterly_results
                (stock_symbol, company_name, quarter, financial_year,
                 source_pdf_url, exchange, extraction_status,
                 announcement_date, created_at, updated_at)
            VALUES (:sym, :cn, :q, :fy, :pdf, :ex, 'pending',
                    :ann, NOW(), NOW())
            ON CONFLICT (stock_symbol, quarter, financial_year, announcement_date)
            DO NOTHING
        """), {
            "sym": symbol, "cn": company_name or "", "q": quarter, "fy": fy,
            "pdf": pdf_url, "ex": exchange, "ann": ann_dt,
        })
    except Exception as e:
        logger.warning(f"Could not insert pending placeholder for {symbol}: {e}")


async def process_bse_results_data(bse_data: List[Dict]) -> List[Dict]:
    """
    Process BSE 'Result' category — these trigger quarterly extraction.
    Returns items that need extraction (with symbol + pdf_url).
    """
    if not bse_data:
        return []

    extraction_items = []
    msg_items: list[dict] = []

    async with get_db_session() as db:
        for row in bse_data:
            scrip_code = str(row.get("SCRIP_CD", "")).strip()
            company_name = row.get("SLONGNAME", "").strip()
            subject = row.get("NEWSSUB", "").strip()
            news_dt = row.get("NEWS_DT", "").strip()
            pdf_url = _build_bse_pdf_url(row.get("ATTACHMENTNAME", ""))

            if not scrip_code or not pdf_url:
                continue

            # Dedup against the bse_announcements_log table
            result = await db.execute(text("""
                INSERT INTO bse_announcements_log
                (scrip_code, company_name, announcement_type, announcement_date, subject, pdf_url, exchange, processed, created_at)
                VALUES (:sc, :cn, 'result', :ad, :sub, :pdf, 'BSE', 0, NOW())
                ON CONFLICT (scrip_code, announcement_type, pdf_url) DO NOTHING
                RETURNING id
            """), {
                "sc": scrip_code, "cn": company_name,
                "ad": news_dt, "sub": subject, "pdf": pdf_url,
            })
            new_row = result.scalar()

            symbol = _scrip_to_symbol(scrip_code, company_name)

            # Always make sure the announcement appears on the feed (Quarterly Result page)
            await _upsert_message_for_extraction(
                db, symbol, company_name, subject, pdf_url, news_dt,
                default_option="quarterly_result",
            )
            await db.commit()

            if new_row is None:
                continue  # duplicate — feed row may have been added but extraction was already triggered before

            # Insert a 'pending' placeholder so PE Pending shows QUEUED badge
            # immediately, before the worker even starts.
            await _insert_pending_qr_placeholder(
                db, symbol, company_name, pdf_url, news_dt, exchange="BSE",
            )
            await db.commit()

            extraction_items.append({
                "symbol": symbol,
                "company_name": company_name,
                "pdf_url": pdf_url,
                "announcement_date": news_dt,
            })
            msg_items.append({
                "symbol": symbol, "company_name": company_name,
                "description": subject, "file_url": pdf_url,
                "exchange": "BSE", "option": "quarterly_result",
            })

    if extraction_items:
        await invalidate_pe_analysis()
    if msg_items:
        await invalidate_messages()
        for m in msg_items:
            await notify_new_message(m)

    logger.info(f"BSE results: {len(bse_data)} fetched, {len(extraction_items)} new for extraction")
    return extraction_items


async def process_bse_board_meeting_data(bse_data: List[Dict]) -> List[Dict]:
    """
    Process BSE 'Board Meeting' category — filter for 'financial result' keyword.
    Returns items matching financial results for extraction.
    """
    if not bse_data:
        return []

    extraction_items = []
    msg_items: list[dict] = []

    async with get_db_session() as db:
        for row in bse_data:
            scrip_code = str(row.get("SCRIP_CD", "")).strip()
            company_name = row.get("SLONGNAME", "").strip()
            subject = row.get("NEWSSUB", "").strip()
            news_dt = row.get("NEWS_DT", "").strip()
            pdf_url = _build_bse_pdf_url(row.get("ATTACHMENTNAME", ""))

            if not scrip_code:
                continue

            subj_lower = subject.lower()

            # Keep only actual result outcomes; skip plain board meeting notices
            if "financial result" not in subj_lower:
                continue

            # Exclude advance intimation notices — they don't contain actual results
            if "intimation" in subj_lower:
                continue

            if not pdf_url:
                continue

            # Dedup against the bse_announcements_log table
            result = await db.execute(text("""
                INSERT INTO bse_announcements_log
                (scrip_code, company_name, announcement_type, announcement_date, subject, pdf_url, exchange, processed, created_at)
                VALUES (:sc, :cn, 'board_meeting', :ad, :sub, :pdf, 'BSE', 0, NOW())
                ON CONFLICT (scrip_code, announcement_type, pdf_url) DO NOTHING
                RETURNING id
            """), {
                "sc": scrip_code, "cn": company_name,
                "ad": news_dt, "sub": subject, "pdf": pdf_url,
            })
            new_row = result.scalar()

            symbol = _scrip_to_symbol(scrip_code, company_name)

            # Make sure the item appears on the Outcome of Board Meeting feed page
            await _upsert_message_for_extraction(
                db, symbol, company_name, subject, pdf_url, news_dt,
                default_option="board_meeting",
            )
            await db.commit()

            if new_row is None:
                continue

            # 'pending' placeholder so PE Pending shows QUEUED before worker runs.
            await _insert_pending_qr_placeholder(
                db, symbol, company_name, pdf_url, news_dt, exchange="BSE",
            )
            await db.commit()

            extraction_items.append({
                "symbol": symbol,
                "company_name": company_name,
                "pdf_url": pdf_url,
                "announcement_date": news_dt,
            })
            msg_items.append({
                "symbol": symbol, "company_name": company_name,
                "description": subject, "file_url": pdf_url,
                "exchange": "BSE", "option": "board_meeting",
            })

    if extraction_items:
        await invalidate_pe_analysis()
    if msg_items:
        await invalidate_messages()
        for m in msg_items:
            await notify_new_message(m)

    logger.info(f"BSE board meeting: {len(bse_data)} fetched, {len(extraction_items)} new for extraction")
    return extraction_items


IST = timezone(timedelta(hours=5, minutes=30))


def _parse_bse_datetime(dt_str: str) -> datetime:
    """Parse BSE NEWS_DT field (IST). Returns timezone-aware datetime."""
    formats = [
        "%d-%b-%Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",
        "%d-%b-%Y",
        "%d %b %Y",
        "%Y-%m-%dT%H:%M:%S",
    ]
    if not dt_str:
        return datetime.now(IST)
    for fmt in formats:
        try:
            parsed = datetime.strptime(dt_str.strip(), fmt)
            return parsed.replace(tzinfo=IST)
        except (ValueError, AttributeError):
            continue
    return datetime.now(IST)


def _scrip_to_symbol(scrip_code: str, company_name: str) -> str:
    """Convert BSE scrip code to trading symbol (lookup from stocks table or fallback)."""
    return scrip_code
