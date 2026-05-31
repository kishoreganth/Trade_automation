"""
BSE corporate announcements fetcher.
Extracted from: nse_url_test.py (fetch_bse_announcements, process_bse_ca_data,
    process_bse_results_data, process_bse_board_meeting_data)
"""

import asyncio
import logging
import tempfile
from typing import List, Dict
from datetime import datetime, timezone, timedelta

import httpx
from bse import BSE
from bse.constants import CATEGORY
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


_BSE_LIB_DOWNLOAD_DIR = tempfile.mkdtemp(prefix="bse_lib_")

_BSE_CATEGORY_MAP = {
    "result": CATEGORY.RESULT,
    "board_meeting": CATEGORY.BOARD_MEETING,
}


_MAX_BSE_PAGES_SAFETY = 200  # ~10,000 rows — hard ceiling to prevent infinite loops


def _fetch_via_bse_lib(category: str) -> List[Dict]:
    """
    Sync helper — fetches ALL announcements for a category using the `bse`
    Python library.  Paginates until every row reported by ROWCNT is collected.
    """
    bse_category = _BSE_CATEGORY_MAP.get(category)
    if bse_category is None:
        raise ValueError(f"Unsupported bse-lib category: {category}")

    today = datetime.now()
    all_rows: List[Dict] = []

    try:
        with BSE(_BSE_LIB_DOWNLOAD_DIR) as bse_client:
            total_count = 0
            page_no = 1

            while page_no <= _MAX_BSE_PAGES_SAFETY:
                res = bse_client.announcements(
                    page_no=page_no,
                    from_date=today,
                    to_date=today,
                    segment="equity",
                    category=bse_category,
                )
                table = res.get("Table", [])
                if not table:
                    break

                if page_no == 1:
                    table1 = res.get("Table1", [])
                    if table1:
                        total_count = table1[0].get("ROWCNT", 0)
                    logger.info(
                        f"BSE lib ({category}): {total_count} total announcements reported"
                    )

                all_rows.extend(table)

                if total_count and len(all_rows) >= total_count:
                    break
                if len(table) < 50:
                    break

                page_no += 1
    except Exception as e:
        logger.error(
            f"BSE lib fetch failed ({category}, page {page_no}): "
            f"{type(e).__name__}: {e or '<no message>'}"
        )

    logger.info(f"BSE lib ({category}): fetched {len(all_rows)}/{total_count} rows across {page_no} pages")
    return all_rows


async def fetch_bse_announcements(category: str = "all", max_pages: int = 10) -> List[Dict]:
    """
    Fetch BSE corporate announcements by category (paginated).
    category: 'all', 'result', 'board_meeting'

    - 'result' and 'board_meeting' use the `bse` Python library — fetches
      ALL pages (driven by ROWCNT, no artificial cap).
    - 'all' uses direct httpx calls to the BSE API (capped by max_pages).
    """
    if category in _BSE_CATEGORY_MAP:
        return await asyncio.to_thread(_fetch_via_bse_lib, category)

    return await _fetch_bse_all_httpx(max_pages)


async def _fetch_bse_all_httpx(max_pages: int = 10) -> List[Dict]:
    """Fetch all BSE announcements via httpx (original direct-API path)."""
    today = datetime.now().strftime("%Y%m%d")
    all_rows: List[Dict] = []
    page_no = 1

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for page_no in range(1, max_pages + 1):
                params = {
                    "pageno": str(page_no),
                    "strCat": "-1",
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
            f"BSE httpx fetch failed (all, page {page_no}): "
            f"{type(e).__name__}: {e or '<no message>'}"
        )

    return all_rows


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
        # Step 1: Filter valid rows and prepare announcement log params
        valid_rows = []
        for row in bse_data:
            scrip_code = str(row.get("SCRIP_CD", "")).strip()
            if not scrip_code:
                continue
            company_name = row.get("SLONGNAME", row.get("NEWSID", "")).strip()
            subject = row.get("NEWSSUB", "").strip()
            news_dt = row.get("NEWS_DT", "").strip()
            pdf_url = _build_bse_pdf_url(row.get("ATTACHMENTNAME", ""))
            valid_rows.append({
                "scrip_code": scrip_code, "company_name": company_name,
                "subject": subject, "news_dt": news_dt, "pdf_url": pdf_url,
            })

        if not valid_rows:
            return []

        # Step 2: Bulk insert into bse_announcements_log (ON CONFLICT DO NOTHING)
        ann_params = [
            {"sc": r["scrip_code"], "cn": r["company_name"], "at": "all",
             "ad": r["news_dt"], "sub": r["subject"], "pdf": r["pdf_url"]}
            for r in valid_rows
        ]
        try:
            for params in ann_params:
                await db.execute(text("""
                    INSERT INTO bse_announcements_log
                    (scrip_code, company_name, announcement_type, announcement_date, subject, pdf_url, exchange, processed, created_at)
                    VALUES (:sc, :cn, :at, :ad, :sub, :pdf, 'BSE', 0, NOW())
                    ON CONFLICT (scrip_code, announcement_type, pdf_url) DO NOTHING
                """), params)
            await db.commit()
        except Exception:
            await db.rollback()

        # Step 3: Resolve symbols (uses in-memory cache, hits DB only on miss)
        for r in valid_rows:
            r["symbol"] = await _scrip_to_symbol(db, r["scrip_code"], r["company_name"])
            r["ann_time"] = _parse_bse_datetime(r["news_dt"])
            r["option"] = classify_announcement(r["subject"])

        # Step 4: Bulk check existing messages
        pdf_urls = [r["pdf_url"] for r in valid_rows]
        symbols = [r["symbol"] for r in valid_rows]
        existing_set = set()
        if pdf_urls:
            existing_result = await db.execute(
                text("SELECT symbol, file_url FROM messages WHERE file_url = ANY(:urls)"),
                {"urls": pdf_urls}
            )
            existing_set = {(row.symbol, row.file_url) for row in existing_result.fetchall()}

        # Step 5: Insert new messages in batch
        for r in valid_rows:
            if (r["symbol"], r["pdf_url"]) in existing_set:
                continue

            result = await db.execute(text("""
                INSERT INTO messages (chat_id, message, timestamp, symbol, company_name, description, file_url, option, exchange)
                VALUES (:cid, :msg, :ts, :sym, :cn, :desc, :url, :opt, 'BSE')
                RETURNING id
            """), {
                "cid": "bse_corporate", "msg": f"{r['symbol']}: {r['subject']}",
                "ts": r["ann_time"], "sym": r["symbol"], "cn": r["company_name"],
                "desc": r["subject"], "url": r["pdf_url"], "opt": r["option"],
            })
            msg_id = result.scalar()

            item = {
                "id": msg_id, "symbol": r["symbol"], "company_name": r["company_name"],
                "description": r["subject"], "file_url": r["pdf_url"], "option": r["option"],
                "exchange": "BSE", "timestamp": r["ann_time"].isoformat(),
            }
            new_items.append(item)

        if new_items:
            await db.commit()

    if new_items:
        await invalidate_messages()
        for item in new_items:
            await notify_new_message(item)
            await send_announcement_notification(item["symbol"], item["company_name"], item["description"], "BSE")

    # Dispatch concall extraction for concall/result_concall items
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
                exchange=item.get("exchange", "BSE"),
                company_name=item.get("company_name", ""),
                announcement_date=item.get("timestamp"),
                message_id=item.get("id"),
            )
        logger.info(f"Dispatched {len(concall_items)} concall extractions")

    # Dispatch announcement insight extraction for investor_presentation + monthly_business_update
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
                exchange=item.get("exchange", "BSE"),
                company_name=item.get("company_name", ""),
                announcement_date=item.get("timestamp"),
                message_id=item.get("id"),
            )
        logger.info(f"Dispatched {len(ann_insight_items)} announcement insight extractions")

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
    ann_dt = ann_dt.replace(hour=0, minute=0, second=0, microsecond=0)
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

            symbol = await _scrip_to_symbol(db, scrip_code, company_name)

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

            symbol = await _scrip_to_symbol(db, scrip_code, company_name)

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


_SCRIP_SYMBOL_CACHE: dict[str, str] = {}


async def _scrip_to_symbol(db, scrip_code: str, company_name: str) -> str:
    """Convert BSE scrip code to trading symbol using stocks table.

    Three-layer resolution:
    1. bse_token lookup (exact)
    2. company_name fuzzy match (fallback for missing bse_token)
    3. Return scrip_code as-is (last resort)
    """
    if scrip_code in _SCRIP_SYMBOL_CACHE:
        return _SCRIP_SYMBOL_CACHE[scrip_code]

    # Layer 1: bse_token lookup
    try:
        scrip_int = int(scrip_code)
        row = await db.execute(
            text("SELECT symbol FROM stocks WHERE bse_token = :bse LIMIT 1"),
            {"bse": scrip_int},
        )
        symbol = row.scalar()
        if symbol:
            _SCRIP_SYMBOL_CACHE[scrip_code] = symbol
            return symbol
    except (ValueError, TypeError):
        pass

    # Layer 2: company_name fuzzy match
    if company_name:
        clean_name = company_name.split(" Limited")[0].split(" Ltd")[0].strip()
        if len(clean_name) >= 3:
            row = await db.execute(
                text("SELECT symbol FROM stocks WHERE company_name ILIKE :pattern LIMIT 1"),
                {"pattern": f"%{clean_name}%"},
            )
            symbol = row.scalar()
            if symbol:
                _SCRIP_SYMBOL_CACHE[scrip_code] = symbol
                return symbol

    # Layer 3: fallback to scrip code
    _SCRIP_SYMBOL_CACHE[scrip_code] = scrip_code
    return scrip_code
