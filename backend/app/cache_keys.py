"""
Cache key constants and invalidation helpers.
When data changes, call the appropriate invalidate_* function.
"""

from .cache import cache_delete_pattern, publish_ws_event

# Cache key prefixes (match @cached decorator prefixes)
MESSAGES_LIST = "messages:list"
MESSAGES_STATS = "messages:stats"
PE_PENDING = "pe:pending"
PE_REVIEWED = "pe:reviewed"
PE_FILTERS = "pe:filters"
REPORT_SUMMARY = "report:summary"
STOCKS_LIST = "stocks:list"


async def invalidate_messages():
    """Call when new message is saved."""
    await cache_delete_pattern("messages:*")


async def invalidate_pe_analysis():
    """Call when quarterly_results changes (extraction, edit, delete)."""
    await cache_delete_pattern("pe:*")
    await cache_delete_pattern("report:*")


async def invalidate_stocks():
    """Call when stocks table changes."""
    await cache_delete_pattern("stocks:*")
    await cache_delete_pattern("pe:filters:*")


async def invalidate_all():
    """Nuclear option — clear all cache."""
    await cache_delete_pattern("*")


async def notify_new_message(message_data: dict):
    """Invalidate cache + push real-time update."""
    await invalidate_messages()
    await publish_ws_event({"type": "new_message", "message": message_data})


async def notify_extraction_update(stock_symbol: str, status: str):
    """Invalidate PE cache + push extraction status."""
    await invalidate_pe_analysis()
    await publish_ws_event({
        "type": "extraction_status_update",
        "stock_symbol": stock_symbol,
        "status": status,
    })


async def notify_quarterly_results(data: dict):
    """Invalidate PE cache + push quarterly results update."""
    await invalidate_pe_analysis()
    await publish_ws_event({"type": "quarterly_results", "data": data})


async def notify_job_event(event_type: str, job_data: dict):
    """Push job status (completed/failed/progress) to frontend."""
    await publish_ws_event({"type": event_type, "job": job_data})
