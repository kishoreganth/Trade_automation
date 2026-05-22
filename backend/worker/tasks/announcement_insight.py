"""
Announcement insight extraction tasks — extract insights from Investor Presentation
and Monthly Business Update PDFs.
"""

import logging
import asyncio
import threading
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import text

from app.cache import init_redis, publish_ws_event
from app.database import get_db_session
from app.services.announcement_extractor import (
    download_pdf_bytes,
    _detect_extraction_mode,
    _extract_full_text,
    _select_pages_for_vision,
    extract_announcement_vision,
    extract_announcement_text,
    save_announcement_insight,
)
from app.services.ocr_extractor import _render_pages_to_png

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
    name="worker.tasks.announcement_insight.run_announcement_extraction",
    bind=True,
    max_retries=2,
    default_retry_delay=90,
    acks_late=True,
    time_limit=360,
    soft_time_limit=300,
)
def run_announcement_extraction(
    self,
    stock_symbol: str,
    pdf_url: str,
    announcement_type: str,
    exchange: str = "BSE",
    company_name: str = "",
    announcement_date: str = None,
    message_id: int = None,
):
    """
    Extract insights from an Investor Presentation or Monthly Business Update PDF.

    Flow:
    1. Download PDF
    2. Detect extraction mode (vision vs text)
    3. Extract via appropriate AI pipeline
    4. Save to announcement_insights table
    5. Notify frontend via WebSocket
    """
    try:
        logger.info(f"Starting announcement extraction: {stock_symbol} ({announcement_type}, {exchange})")
        _run_async(_do_announcement_extraction(
            stock_symbol, pdf_url, announcement_type, exchange,
            company_name, announcement_date, message_id,
        ))
        logger.info(f"Announcement extraction complete: {stock_symbol} ({announcement_type})")
    except Exception as exc:
        logger.error(f"Announcement extraction failed for {stock_symbol} ({announcement_type}): {exc}")
        _run_async(_mark_failed(stock_symbol, pdf_url, announcement_type, str(exc)))
        raise self.retry(exc=exc)


async def _do_announcement_extraction(
    stock_symbol: str,
    pdf_url: str,
    announcement_type: str,
    exchange: str,
    company_name: str,
    announcement_date: str,
    message_id: int,
):
    """Async implementation of announcement extraction."""
    await _ensure_redis()

    # Mark as processing
    try:
        async with get_db_session() as db:
            await db.execute(text("""
                UPDATE announcement_insights
                SET extraction_status = 'processing', updated_at = NOW()
                WHERE stock_symbol = :sym AND source_pdf_url = :pdf
                  AND announcement_type = :ann_type
                  AND extraction_status = 'pending'
            """), {"sym": stock_symbol, "pdf": pdf_url, "ann_type": announcement_type})
            await db.commit()
    except Exception:
        pass

    # 1. Download PDF
    pdf_bytes = await download_pdf_bytes(pdf_url)
    if not pdf_bytes:
        raise ValueError(f"Could not download PDF: {pdf_url}")

    # 2. Detect extraction mode
    mode, total_pages = _detect_extraction_mode(pdf_bytes)
    logger.info(f"Detected mode={mode} for {stock_symbol} ({total_pages} pages)")

    # 3. Extract via appropriate pipeline
    extraction_data = None
    pages_processed = 0

    if mode == "vision":
        page_indices = _select_pages_for_vision(pdf_bytes)
        pages_processed = len(page_indices)
        extraction_data = await extract_announcement_vision(
            pdf_bytes, stock_symbol, company_name, page_indices
        )
    else:
        text_content = _extract_full_text(pdf_bytes)
        pages_processed = total_pages
        extraction_data = await extract_announcement_text(
            text_content, stock_symbol, company_name
        )

    if not extraction_data:
        raise ValueError(f"AI extraction returned empty for {stock_symbol} ({announcement_type})")

    # 4. Parse announcement date
    ann_dt = None
    if announcement_date:
        try:
            ann_dt = datetime.fromisoformat(announcement_date)
            if ann_dt.tzinfo is None:
                ann_dt = ann_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    # 5. Save to DB
    row_id = await save_announcement_insight(
        stock_symbol=stock_symbol,
        company_name=company_name,
        exchange=exchange,
        pdf_url=pdf_url,
        announcement_type=announcement_type,
        message_id=message_id,
        announcement_date=ann_dt,
        extraction_data=extraction_data,
        extraction_mode=mode,
        pages_processed=pages_processed,
    )

    # 5b. Clean up TBD placeholder if it exists (created by manual trigger)
    try:
        async with get_db_session() as db:
            await db.execute(text("""
                DELETE FROM announcement_insights
                WHERE stock_symbol = :sym AND source_pdf_url = :pdf
                  AND announcement_type = :ann_type
                  AND quarter = 'TBD' AND financial_year = 'TBD'
            """), {"sym": stock_symbol, "pdf": pdf_url, "ann_type": announcement_type})
            await db.commit()
    except Exception:
        pass

    # 6. Notify frontend
    await publish_ws_event({
        "type": "announcement_insight_ready",
        "stock_symbol": stock_symbol,
        "announcement_type": announcement_type,
        "insight_id": row_id,
        "quarter": extraction_data.get("quarter"),
        "financial_year": extraction_data.get("financial_year"),
    })


async def _mark_failed(stock_symbol: str, pdf_url: str, announcement_type: str, error: str):
    """Mark announcement extraction as failed."""
    err_short = (error or "")[:500]
    try:
        async with get_db_session() as db:
            await db.execute(text("""
                UPDATE announcement_insights
                SET extraction_status = 'failed',
                    extraction_error = :err,
                    updated_at = NOW()
                WHERE stock_symbol = :sym AND source_pdf_url = :pdf
                  AND announcement_type = :ann_type
                  AND extraction_status IN ('pending', 'processing')
            """), {"sym": stock_symbol, "pdf": pdf_url, "ann_type": announcement_type, "err": err_short})
            await db.commit()
    except Exception as e:
        logger.warning(f"Could not mark {stock_symbol} ({announcement_type}) as failed: {e}")


@shared_task(
    name="worker.tasks.announcement_insight.retry_stuck_announcement_extractions",
    bind=True,
    max_retries=0,
    time_limit=60,
)
def retry_stuck_announcement_extractions(self):
    """Re-queue announcement extractions stuck in pending/processing for >3 min."""
    try:
        count = _run_async(_do_retry_stuck_announcements())
        if count > 0:
            logger.info(f"Re-queued {count} stuck announcement extractions")
    except Exception as exc:
        logger.error(f"Retry stuck announcement extractions failed: {exc}")


async def _do_retry_stuck_announcements():
    await _ensure_redis()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
    count = 0

    async with get_db_session() as db:
        rows = await db.execute(text("""
            SELECT stock_symbol, source_pdf_url, announcement_type, exchange,
                   company_name, source_message_id
            FROM announcement_insights
            WHERE extraction_status IN ('pending', 'processing')
              AND COALESCE(updated_at, created_at) < :cutoff
              AND source_pdf_url IS NOT NULL
              AND source_pdf_url <> ''
            LIMIT 20
        """), {"cutoff": cutoff})

        for row in rows.fetchall():
            run_announcement_extraction.delay(
                stock_symbol=row.stock_symbol,
                pdf_url=row.source_pdf_url,
                announcement_type=row.announcement_type or "Investor Presentation",
                exchange=row.exchange or "BSE",
                company_name=row.company_name or "",
                message_id=row.source_message_id,
            )
            count += 1

    return count
