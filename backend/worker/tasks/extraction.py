"""
OCR/PE extraction tasks — CPU-bound work offloaded from API workers.
Replaces: run_quarterly_extraction() direct await in nse_url_test.py.
"""

import logging
import asyncio
import threading
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import text

from app.cache import init_redis, publish_ws_event
from app.cache_keys import (
    notify_extraction_update,
    notify_quarterly_results,
    invalidate_pe_analysis,
)
from app.database import get_db_session
from app.services.ocr_extractor import (
    download_and_convert_pdf,
    download_and_convert_pdf_full,
    extract_financial_data_ai,
    save_quarterly_result,
    fetch_and_save_cmp,
    run_ai_stock_analysis,
    _parse_announcement_date,
)

logger = logging.getLogger(__name__)

_thread_local = threading.local()


def _run_async(coro):
    """Run async code inside Celery task. Thread-local event loop — safe for --pool=threads."""
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _thread_local.loop = loop
    return loop.run_until_complete(coro)


async def _ensure_redis():
    """Ensure Redis client exists for the current thread's event loop."""
    await init_redis()


@shared_task(
    name="worker.tasks.extraction.run_quarterly_extraction",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    time_limit=300,
    soft_time_limit=240,
)
def run_quarterly_extraction(
    self,
    stock_symbol: str,
    pdf_url: str,
    exchange: str = "NSE",
    company_name: str = "",
    announcement_date: str = None,
):
    """
    Extract quarterly financial results from PDF using OCR + OpenAI.
    
    Flow:
    1. Download PDF -> convert to images
    2. OCR via python-doctr
    3. Send to OpenAI for structured extraction
    4. Save to quarterly_results table
    5. Auto-fetch CMP and calculate PE
    6. Notify frontend via Redis PubSub
    """
    try:
        logger.info(f"Starting extraction: {stock_symbol} ({exchange})")
        _run_async(_do_extraction(
            stock_symbol, pdf_url, exchange, company_name, announcement_date
        ))
        logger.info(f"Extraction complete: {stock_symbol}")
    except _NonResultsPDFError as exc:
        logger.warning(f"Skipping non-results PDF for {stock_symbol}: {exc}")
        _run_async(_mark_extraction_failed(
            stock_symbol, pdf_url, f"non-results-pdf: {exc}",
            exchange=exchange, company_name=company_name, announcement_date=announcement_date,
        ))
        return
    except Exception as exc:
        logger.error(f"Extraction failed for {stock_symbol}: {exc}")
        _run_async(_mark_extraction_failed(
            stock_symbol, pdf_url, str(exc),
            exchange=exchange, company_name=company_name, announcement_date=announcement_date,
        ))
        raise self.retry(exc=exc)


class _NonResultsPDFError(Exception):
    """Raised when PDF is clearly not a quarterly results document — skip retry."""
    pass


async def _do_extraction(
    stock_symbol: str,
    pdf_url: str,
    exchange: str,
    company_name: str,
    announcement_date: str,
):
    """
    Async extraction implementation.
    Imports from the service layer (which contains the actual OCR + AI logic
    migrated from nse_url_test.py).
    """
    await _ensure_redis()

    # Flip placeholder row to 'processing' so PE Pending shows EXTRACTING
    # (blue pulse) live. No-op if no row exists yet (will be created by save).
    try:
        async with get_db_session() as db:
            await db.execute(text("""
                UPDATE quarterly_results
                SET extraction_status = 'processing', updated_at = NOW()
                WHERE stock_symbol = :sym
                  AND source_pdf_url = :pdf
                  AND extraction_status IN ('pending', 'queued')
            """), {"sym": stock_symbol, "pdf": pdf_url})
            await db.commit()
    except Exception as e:
        logger.warning(f"Could not flip {stock_symbol} to processing: {e}")

    await notify_extraction_update(stock_symbol, "processing")

    images = await download_and_convert_pdf(pdf_url)
    if not images:
        raise ValueError(f"No images extracted from PDF: {pdf_url}")

    is_short_pdf = len(images) <= 2

    result = await extract_financial_data_ai(images, stock_symbol, company_name)

    def _is_empty(r):
        if not r:
            return True
        return not (r.get("standalone_periods") or r.get("consolidated_periods"))

    if _is_empty(result) and not is_short_pdf:
        logger.warning(f"AI returned empty for {stock_symbol} on filtered pages — retrying with full PDF")
        images_full = await download_and_convert_pdf_full(pdf_url, max_pages=12)
        if images_full:
            result = await extract_financial_data_ai(images_full, stock_symbol, company_name)

    if _is_empty(result):
        if is_short_pdf:
            raise _NonResultsPDFError(f"PDF has {len(images)} page(s), no financial periods found")
        raise ValueError(f"AI extraction returned empty for {stock_symbol} (after fallback)")

    await save_quarterly_result(
        stock_symbol=stock_symbol,
        company_name=company_name,
        exchange=exchange,
        pdf_url=pdf_url,
        announcement_date=announcement_date,
        extraction_data=result,
    )

    await fetch_and_save_cmp(stock_symbol, exchange)

    await notify_extraction_update(stock_symbol, "completed")
    await notify_quarterly_results({
        "stock_symbol": stock_symbol,
        "status": "completed",
        "exchange": exchange,
    })


def _quarter_fy_from_announcement(d) -> tuple:
    """Derive (quarter, financial_year) from announcement date.
    Indian results are announced AFTER quarter ends:
      Apr-Jun  → Q4 results (Jan-Mar just ended), FY = (y-1)-(y)  e.g. May 2026 → Q4, 2025-26
      Jul-Sep  → Q1 results (Apr-Jun), FY = (y)-(y+1)
      Oct-Dec  → Q2 results (Jul-Sep), FY = (y)-(y+1)
      Jan-Mar  → Q3 results (Oct-Dec), FY = (y-1)-(y)"""
    y, m = d.year, d.month
    if 4 <= m <= 6:
        return "Q4", f"{y - 1}-{str(y)[-2:]}"
    if 7 <= m <= 9:
        return "Q1", f"{y}-{str(y + 1)[-2:]}"
    if 10 <= m <= 12:
        return "Q2", f"{y}-{str(y + 1)[-2:]}"
    return "Q3", f"{y - 1}-{str(y)[-2:]}"


async def _mark_extraction_failed(
    stock_symbol: str,
    pdf_url: str,
    error: str,
    exchange: str = "BSE",
    company_name: str = "",
    announcement_date=None,
):
    """Mark extraction as failed in DB AND notify frontend.
    If no row exists for this PDF, INSERT a failed-status row so the stock
    appears on PE Pending page with FAILED badge (matches old app behavior)."""
    err_short = (error or "")[:500]
    ann_dt = _parse_announcement_date(announcement_date) or datetime.now(timezone.utc)

    try:
        async with get_db_session() as db:
            updated = await db.execute(text("""
                UPDATE quarterly_results
                SET extraction_status = 'failed',
                    extraction_error = :err,
                    updated_at = NOW()
                WHERE stock_symbol = :sym
                  AND source_pdf_url = :pdf
                  AND extraction_status IN ('pending', 'processing')
                RETURNING id
            """), {"sym": stock_symbol, "pdf": pdf_url, "err": err_short})
            if updated.first() is None:
                exists = await db.execute(text("""
                    SELECT 1 FROM quarterly_results
                    WHERE stock_symbol = :sym AND source_pdf_url = :pdf LIMIT 1
                """), {"sym": stock_symbol, "pdf": pdf_url})
                if exists.first() is None:
                    quarter, fy = _quarter_fy_from_announcement(ann_dt)
                    await db.execute(text("""
                        INSERT INTO quarterly_results
                            (stock_symbol, company_name, quarter, financial_year, source_pdf_url,
                             exchange, extraction_status, extraction_error,
                             announcement_date, created_at, updated_at)
                        VALUES (:sym, :cn, :q, :fy, :pdf, :ex, 'failed', :err,
                                :ann, NOW(), NOW())
                        ON CONFLICT (stock_symbol, quarter, financial_year, announcement_date)
                        DO UPDATE SET extraction_status='failed', extraction_error=:err, updated_at=NOW()
                    """), {
                        "sym": stock_symbol, "cn": company_name or "",
                        "q": quarter, "fy": fy, "pdf": pdf_url, "ex": exchange,
                        "err": err_short, "ann": ann_dt,
                    })
            await db.commit()
        await invalidate_pe_analysis()
    except Exception as e:
        logger.warning(f"Could not mark {stock_symbol} as failed in DB: {e}")
    try:
        await notify_extraction_update(stock_symbol, "failed")
    except Exception:
        pass


@shared_task(
    name="worker.tasks.extraction.retry_stuck_extractions",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def retry_stuck_extractions(self):
    """
    Periodic task (every 5 min): find extractions stuck in 'processing' for >10 min
    and re-queue them.
    """
    try:
        count = _run_async(_do_retry_stuck())
        if count > 0:
            logger.info(f"Re-queued {count} stuck extractions")
    except Exception as exc:
        logger.error(f"Retry stuck extractions failed: {exc}")


async def _do_retry_stuck():
    """Find and re-queue stuck extractions.
    Catches BOTH 'processing' (worker died mid-task) AND 'pending'
    (queued but never picked up — happens after queue/worker mismatch or broker purge).
    Skips rows whose PDF URL is missing — nothing we can do with those."""
    await _ensure_redis()

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    count = 0

    async with get_db_session() as db:
        rows = await db.execute(text("""
            SELECT stock_symbol, source_pdf_url, exchange, company_name, announcement_date
            FROM quarterly_results
            WHERE extraction_status IN ('processing', 'pending')
              AND COALESCE(updated_at, created_at) < :cutoff
              AND source_pdf_url IS NOT NULL
              AND source_pdf_url <> ''
            LIMIT 50
        """), {"cutoff": cutoff})

        for row in rows.fetchall():
            run_quarterly_extraction.delay(
                stock_symbol=row.stock_symbol,
                pdf_url=row.source_pdf_url,
                exchange=row.exchange or "NSE",
                company_name=row.company_name or "",
                announcement_date=str(row.announcement_date) if row.announcement_date else None,
            )
            count += 1

    return count


@shared_task(
    name="worker.tasks.extraction.run_ai_analysis",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    rate_limit="3/m",
    time_limit=180,
    soft_time_limit=150,
)
def run_ai_analysis(self, stock_symbol: str, analysis_type: str = "valuation"):
    """
    AI-powered stock analysis (valuation, recommendation).
    Separate task from extraction — different rate limit and priority.
    """
    try:
        logger.info(f"Starting AI analysis: {stock_symbol} ({analysis_type})")
        _run_async(_do_ai_analysis(stock_symbol, analysis_type))
        logger.info(f"AI analysis complete: {stock_symbol}")
    except Exception as exc:
        logger.error(f"AI analysis failed for {stock_symbol}: {exc}")
        raise self.retry(exc=exc)


async def _do_ai_analysis(stock_symbol: str, analysis_type: str):
    """Async AI analysis implementation."""
    await _ensure_redis()

    result = await run_ai_stock_analysis(stock_symbol, analysis_type)

    await invalidate_pe_analysis()
    await publish_ws_event({
        "type": "ai_analysis_complete",
        "stock_symbol": stock_symbol,
        "result": result,
    })
