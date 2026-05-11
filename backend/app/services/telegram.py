"""
Telegram notification service.
Extracted from: nse_url_test.py (send_webhook_message, trigger_watchlist_message)
"""

import logging
from typing import Optional

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Log misconfiguration ONCE per process, not per announcement.
# Without this, BSE-all bursts (500+ items/min) flood logs with the same warning.
_misconfig_warned = False


def _is_configured() -> bool:
    """True only when telegram is both enabled AND has the credentials it needs.
    On first miss, logs a single WARNING explaining why it's silently skipping."""
    global _misconfig_warned
    if not settings.TELEGRAM_ENABLED:
        return False
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        if not _misconfig_warned:
            missing = []
            if not settings.TELEGRAM_BOT_TOKEN:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not settings.TELEGRAM_CHAT_ID:
                missing.append("TELEGRAM_CHAT_ID")
            logger.warning(
                "Telegram is enabled but missing %s — silently skipping all "
                "telegram sends for the lifetime of this worker. Set "
                "TELEGRAM_ENABLED=false to suppress this warning, or provide "
                "the missing variables.", ", ".join(missing),
            )
            _misconfig_warned = True
        return False
    return True


async def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API."""
    if not _is_configured():
        return False

    url = TELEGRAM_API.format(token=settings.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": chat_id or settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            logger.error(f"Telegram API error: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


async def send_announcement_notification(
    symbol: str,
    company_name: str,
    description: str,
    exchange: str = "NSE",
    file_url: Optional[str] = None,
) -> bool:
    """Format and send announcement notification to configured chat."""
    text = (
        f"<b>{exchange} | {symbol}</b>\n"
        f"{company_name}\n\n"
        f"{description}"
    )
    if file_url:
        text += f"\n\n<a href='{file_url}'>View Document</a>"

    return await send_message(settings.TELEGRAM_CHAT_ID, text)


async def send_extraction_result(
    symbol: str,
    quarter: str,
    financial_year: str,
    eps: float,
    pe: Optional[float] = None,
) -> bool:
    """Send PE extraction result notification."""
    text = (
        f"<b>PE Extracted | {symbol}</b>\n"
        f"Quarter: {quarter} | FY: {financial_year}\n"
        f"EPS: {eps:.2f}"
    )
    if pe:
        text += f" | PE: {pe:.1f}"

    return await send_message(settings.TELEGRAM_CHAT_ID, text)
