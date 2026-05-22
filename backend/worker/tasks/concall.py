"""
Concall transcript extraction tasks — extract insights from conference call PDFs.
"""

import logging
import asyncio
import threading
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import text

from app.cache import init_redis, publish_ws_event
from app.database import get_db_session
from app.services.concall_extractor import (
    extract_text_from_pdf,
    extract_concall_insights_ai,
    save_concall_insight,
    _is_concall_transcript,
    _derive_quarter_fy,
)

logger = logging.getLogger(__name__)

_thread_local = threading.local()


def _run_async(coro):
    """Run async code inside Celery task."""
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _thread_local.loop = loop
    return loop.run_until_complete(coro)


async def _ensure_redis():
    await init_redis()


@shared_task(
    name="worker.tasks.concall.run_concall_extraction",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
    time_limit=240,
    soft_time_limit=200,
)
def run_concall_extraction(
    self,
    stock_symbol: str,
    pdf_url: str,
    exchange: str = "BSE",
    company_name: str = "",
    announcement_date: str = None,
    message_id: int = None,
):
    """
    Extract insights from a concall transcript PDF.

    Flow:
    1. Download PDF and extract text (PyMuPDF)
    2. Validate it's actually a concall transcript
    3. Send to OpenAI for structured extraction
    4. Save to concall_insights table
    5. Notify frontend via WebSocket
    """
    try:
        logger.info(f"Starting concall extraction: {stock_symbol} ({exchange})")
        _run_async(_do_concall_extraction(
            stock_symbol, pdf_url, exchange, company_name,
            announcement_date, message_id,
        ))
        logger.info(f"Concall extraction complete: {stock_symbol}")
    except _NotConcallError as exc:
        logger.warning(f"Skipping non-concall PDF for {stock_symbol}: {exc}")
        _run_async(_mark_concall_failed(
            stock_symbol, pdf_url, f"not-concall: {exc}"
        ))
        return
    except Exception as exc:
        logger.error(f"Concall extraction failed for {stock_symbol}: {exc}")
        _run_async(_mark_concall_failed(stock_symbol, pdf_url, str(exc)))
        raise self.retry(exc=exc)


class _NotConcallError(Exception):
    """Raised when PDF is not a conference call transcript."""
    pass


async def _do_concall_extraction(
    stock_symbol: str,
    pdf_url: str,
    exchange: str,
    company_name: str,
    announcement_date: str,
    message_id: int,
):
    """Async implementation of concall extraction."""
    await _ensure_redis()

    # Mark as processing
    try:
        async with get_db_session() as db:
            await db.execute(text("""
                UPDATE concall_insights
                SET extraction_status = 'processing', updated_at = NOW()
                WHERE stock_symbol = :sym AND source_pdf_url = :pdf
                  AND extraction_status = 'pending'
            """), {"sym": stock_symbol, "pdf": pdf_url})
            await db.commit()
    except Exception:
        pass

    # 1. Extract text from PDF
    transcript = await extract_text_from_pdf(pdf_url)
    if not transcript:
        raise ValueError(f"Could not extract text from PDF: {pdf_url}")

    # 2. Validate it's a concall
    if not _is_concall_transcript(transcript):
        raise _NotConcallError(f"PDF does not appear to be a concall transcript")

    # 3. AI extraction
    result = await extract_concall_insights_ai(transcript, stock_symbol, company_name)
    if not result:
        raise ValueError(f"AI extraction returned empty for concall {stock_symbol}")

    # If AI didn't determine quarter/FY, try regex from transcript
    if not result.get("quarter") or not result.get("financial_year"):
        q, fy = _derive_quarter_fy(transcript)
        if q and not result.get("quarter"):
            result["quarter"] = q
        if fy and not result.get("financial_year"):
            result["financial_year"] = fy

    if not result.get("quarter") or not result.get("financial_year"):
        raise ValueError(f"Could not determine quarter/FY for concall {stock_symbol}")

    # 4. Parse announcement date
    ann_dt = None
    if announcement_date:
        from app.services.ocr_extractor import _parse_announcement_date
        ann_dt = _parse_announcement_date(announcement_date)

    # 5. Save to DB
    row_id = await save_concall_insight(
        stock_symbol=stock_symbol,
        company_name=company_name,
        exchange=exchange,
        pdf_url=pdf_url,
        message_id=message_id,
        announcement_date=ann_dt,
        extraction_data=result,
        transcript_length=len(transcript),
    )

    # 5b. Clean up TBD placeholder if it exists (created by manual trigger)
    try:
        async with get_db_session() as db:
            await db.execute(text("""
                DELETE FROM concall_insights
                WHERE stock_symbol = :sym AND source_pdf_url = :pdf
                  AND quarter = 'TBD' AND financial_year = 'TBD'
            """), {"sym": stock_symbol, "pdf": pdf_url})
            await db.commit()
    except Exception:
        pass

    # 6. Notify frontend
    await publish_ws_event({
        "type": "concall_insight_ready",
        "stock_symbol": stock_symbol,
        "insight_id": row_id,
        "quarter": result.get("quarter"),
        "financial_year": result.get("financial_year"),
    })


async def _mark_concall_failed(stock_symbol: str, pdf_url: str, error: str):
    """Mark concall extraction as failed."""
    err_short = (error or "")[:500]
    try:
        async with get_db_session() as db:
            await db.execute(text("""
                UPDATE concall_insights
                SET extraction_status = 'failed',
                    extraction_error = :err,
                    updated_at = NOW()
                WHERE stock_symbol = :sym AND source_pdf_url = :pdf
                  AND extraction_status IN ('pending', 'processing')
            """), {"sym": stock_symbol, "pdf": pdf_url, "err": err_short})
            await db.commit()
    except Exception as e:
        logger.warning(f"Could not mark concall {stock_symbol} as failed: {e}")


@shared_task(
    name="worker.tasks.concall.retry_stuck_concall_extractions",
    bind=True,
    max_retries=0,
    time_limit=60,
)
def retry_stuck_concall_extractions(self):
    """Re-queue concall extractions stuck in pending/processing for >3 min."""
    try:
        count = _run_async(_do_retry_stuck_concall())
        if count > 0:
            logger.info(f"Re-queued {count} stuck concall extractions")
    except Exception as exc:
        logger.error(f"Retry stuck concall extractions failed: {exc}")


async def _do_retry_stuck_concall():
    await _ensure_redis()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
    count = 0

    async with get_db_session() as db:
        rows = await db.execute(text("""
            SELECT stock_symbol, source_pdf_url, exchange, company_name,
                   source_message_id
            FROM concall_insights
            WHERE extraction_status IN ('pending', 'processing')
              AND COALESCE(updated_at, created_at) < :cutoff
              AND source_pdf_url IS NOT NULL
              AND source_pdf_url <> ''
            LIMIT 20
        """), {"cutoff": cutoff})

        for row in rows.fetchall():
            run_concall_extraction.delay(
                stock_symbol=row.stock_symbol,
                pdf_url=row.source_pdf_url,
                exchange=row.exchange or "BSE",
                company_name=row.company_name or "",
                message_id=row.source_message_id,
            )
            count += 1

    return count
