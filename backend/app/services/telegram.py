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


async def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API."""
    if not settings.TELEGRAM_ENABLED:
        logger.debug(f"Telegram disabled, skipping: {text[:50]}...")
        return False

    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set")
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
