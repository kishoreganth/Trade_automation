"""
Announcement fetch tasks — NSE & BSE.
Replaces: run_periodic_task_equities, run_periodic_task_bse_all,
           run_periodic_task_bse_results, run_periodic_task_bse_board_meeting
"""

import logging
import asyncio
import threading
from celery import shared_task

from app.cache import init_redis
from app.services.nse_fetcher import (
    fetch_nse_announcements,
    process_nse_announcements,
    process_nse_for_extraction,
)
from app.services.bse_fetcher import (
    fetch_bse_announcements,
    process_bse_ca_data,
    process_bse_results_data,
    process_bse_board_meeting_data,
)
from worker.tasks.extraction import run_quarterly_extraction

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
    name="worker.tasks.announcements.fetch_nse_equities",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def fetch_nse_equities(self):
    """
    Job 1: Fetch NSE corporate announcements (equities segment).
    Equivalent to run_periodic_task_equities() in nse_url_test.py.
    """
    try:
        logger.info("Starting NSE equities fetch...")
        _run_async(_do_fetch_nse_equities())
        logger.info("NSE equities fetch completed")
    except Exception as exc:
        logger.error(f"NSE equities fetch failed: {exc}")
        raise self.retry(exc=exc)


async def _do_fetch_nse_equities():
    """Async implementation — imports the actual fetch logic."""
    await _ensure_redis()

    announcements = await fetch_nse_announcements(segment="equities")
    new_items = await process_nse_announcements(announcements)

    # Dispatch extraction for NSE quarterly results (keyword-filtered)
    extraction_items = await process_nse_for_extraction(announcements)
    for item in extraction_items:
        run_quarterly_extraction.delay(
            stock_symbol=item["symbol"],
            pdf_url=item["pdf_url"],
            exchange="NSE",
            company_name=item.get("company_name", ""),
            announcement_date=item.get("announcement_date"),
        )

    return len(new_items)


@shared_task(
    name="worker.tasks.announcements.fetch_bse_all_announcements",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def fetch_bse_all_announcements(self):
    """
    Job 2: Fetch ALL BSE corporate announcements.
    Equivalent to run_periodic_task_bse_all() in nse_url_test.py.
    """
    try:
        logger.info("Starting BSE all announcements fetch...")
        _run_async(_do_fetch_bse_all())
        logger.info("BSE all announcements fetch completed")
    except Exception as exc:
        logger.error(f"BSE all fetch failed: {exc}")
        raise self.retry(exc=exc)


async def _do_fetch_bse_all():
    """Async implementation for BSE all announcements."""
    await _ensure_redis()

    announcements = await fetch_bse_announcements(category="all")
    new_items = await process_bse_ca_data(announcements)
    return len(new_items)


@shared_task(
    name="worker.tasks.announcements.fetch_bse_results",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def fetch_bse_results(self):
    """
    Job 3: Fetch BSE RESULT-category announcements.
    Equivalent to run_periodic_task_bse_results() in nse_url_test.py.
    """
    try:
        logger.info("Starting BSE results fetch...")
        count = _run_async(_do_fetch_bse_results())
        logger.info(f"BSE results fetch completed: {count} new items")
    except Exception as exc:
        logger.error(f"BSE results fetch failed: {exc}")
        raise self.retry(exc=exc)


async def _do_fetch_bse_results():
    """Async implementation for BSE result announcements."""
    await _ensure_redis()

    announcements = await fetch_bse_announcements(category="result")
    new_items = await process_bse_results_data(announcements)

    for item in new_items:
        run_quarterly_extraction.delay(
            stock_symbol=item["symbol"],
            pdf_url=item["pdf_url"],
            exchange="BSE",
            company_name=item.get("company_name", ""),
            announcement_date=item.get("announcement_date"),
        )

    return len(new_items)


@shared_task(
    name="worker.tasks.announcements.fetch_bse_board_meeting",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def fetch_bse_board_meeting(self):
    """
    Job 4: Fetch BSE BOARD_MEETING-category, filter for 'financial result'.
    Equivalent to run_periodic_task_bse_board_meeting() in nse_url_test.py.
    """
    try:
        logger.info("Starting BSE board meeting fetch...")
        count = _run_async(_do_fetch_bse_board_meeting())
        logger.info(f"BSE board meeting fetch completed: {count} new items")
    except Exception as exc:
        logger.error(f"BSE board meeting fetch failed: {exc}")
        raise self.retry(exc=exc)


async def _do_fetch_bse_board_meeting():
    """Async implementation for BSE board meeting announcements."""
    await _ensure_redis()

    announcements = await fetch_bse_announcements(category="board_meeting")
    new_items = await process_bse_board_meeting_data(announcements)

    for item in new_items:
        run_quarterly_extraction.delay(
            stock_symbol=item["symbol"],
            pdf_url=item["pdf_url"],
            exchange="BSE",
            company_name=item.get("company_name", ""),
            announcement_date=item.get("announcement_date"),
        )

    return len(new_items)
