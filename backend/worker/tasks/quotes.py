"""
Fetch quotes tasks — I/O-bound API calls to broker.
Replaces: scheduled fetch quotes logic in nse_url_test.py.
"""

import logging
import asyncio
import threading
from celery import shared_task

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
    from app.cache import init_redis
    await init_redis()


@shared_task(
    name="worker.tasks.quotes.scheduled_fetch_quotes",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
    time_limit=600,      # 10 min hard limit
    soft_time_limit=540,  # 9 min soft limit
)
def scheduled_fetch_quotes(self):
    """
    Scheduled daily quote fetch (weekdays 12:40 IST).
    Replaces: scheduled_fetch_quotes_task() in nse_url_test.py.
    
    Flow:
    1. Check if fetch is enabled in config
    2. Load Google Sheet stock list
    3. Fetch quotes from Kotak Neo API (rate-limited batches)
    4. Update Google Sheet with prices
    5. Notify frontend via WebSocket
    """
    try:
        logger.info("Starting scheduled fetch quotes...")
        result = _run_async(_do_scheduled_fetch())
        logger.info(f"Scheduled fetch quotes completed: {result}")
        return result
    except Exception as exc:
        logger.error(f"Scheduled fetch quotes failed: {exc}")
        raise self.retry(exc=exc)


async def _do_scheduled_fetch():
    """Async implementation for scheduled quote fetch."""
    await _ensure_redis()
    from app.services.quote_fetcher import (
        is_fetch_enabled,
        load_gsheet_stocks,
        fetch_quotes_batched,
        update_gsheet_with_prices,
    )
    from app.cache import publish_ws_event

    if not await is_fetch_enabled():
        logger.info("Scheduled fetch disabled in config — skipping")
        return {"status": "skipped", "reason": "disabled"}

    await publish_ws_event({
        "type": "scheduled_task",
        "status": "started",
        "message": "Fetching stock quotes...",
    })

    stocks_df = await load_gsheet_stocks()
    total = len(stocks_df)

    await publish_ws_event({
        "type": "scheduled_task",
        "status": "progress",
        "message": f"Loaded {total} stocks from sheet",
    })

    quotes = await fetch_quotes_batched(stocks_df, requests_per_minute=190)

    await publish_ws_event({
        "type": "scheduled_task",
        "status": "progress",
        "message": f"Fetched quotes for {len(quotes)} stocks",
    })

    await update_gsheet_with_prices(stocks_df, quotes)

    await publish_ws_event({
        "type": "scheduled_task",
        "status": "completed",
        "message": f"Updated {len(quotes)}/{total} stock prices",
    })

    return {"status": "completed", "total": total, "fetched": len(quotes)}


@shared_task(
    name="worker.tasks.quotes.fetch_quotes_manual",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
)
def fetch_quotes_manual(self, job_id: str = None):
    """
    Manual quote fetch triggered from dashboard button.
    Same logic as scheduled but triggered on-demand.
    """
    try:
        logger.info(f"Starting manual fetch quotes (job: {job_id})...")
        result = _run_async(_do_manual_fetch(job_id))
        logger.info(f"Manual fetch quotes completed: {result}")
        return result
    except Exception as exc:
        logger.error(f"Manual fetch quotes failed: {exc}")
        _run_async(_notify_job_failed(job_id, str(exc)))
        raise self.retry(exc=exc)


async def _do_manual_fetch(job_id: str):
    """Manual fetch implementation with job progress updates."""
    await _ensure_redis()
    from app.services.quote_fetcher import (
        load_gsheet_stocks,
        fetch_quotes_batched,
        update_gsheet_with_prices,
    )
    from app.cache_keys import notify_job_event

    await notify_job_event("job_progress", {
        "id": job_id, "status": "running", "progress": 10,
        "message": "Loading stock list...",
    })

    stocks_df = await load_gsheet_stocks()

    await notify_job_event("job_progress", {
        "id": job_id, "status": "running", "progress": 30,
        "message": f"Fetching quotes for {len(stocks_df)} stocks...",
    })

    quotes = await fetch_quotes_batched(stocks_df, requests_per_minute=190)

    await notify_job_event("job_progress", {
        "id": job_id, "status": "running", "progress": 80,
        "message": "Updating sheet...",
    })

    await update_gsheet_with_prices(stocks_df, quotes)

    await notify_job_event("job_completed", {
        "id": job_id, "status": "completed", "progress": 100,
        "message": f"Done — {len(quotes)}/{len(stocks_df)} prices updated",
    })

    return {"fetched": len(quotes), "total": len(stocks_df)}


async def _notify_job_failed(job_id: str, error: str):
    """Notify frontend of job failure."""
    await _ensure_redis()
    from app.cache_keys import notify_job_event
    try:
        await notify_job_event("job_failed", {
            "id": job_id, "status": "failed", "message": error,
        })
    except Exception:
        pass
