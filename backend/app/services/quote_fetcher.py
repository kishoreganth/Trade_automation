"""
Stock quote fetching service.
Extracted from: nse_url_test.py (get_quotes_with_rate_limit, scheduled fetch logic,
    GSheet integration via gsheet_stock_get.py)
"""

import logging
import asyncio
from typing import Dict, List, Optional

import httpx
from sqlalchemy import text

from ..database import get_db_session
from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def is_fetch_enabled() -> bool:
    """Check if scheduled fetch is enabled in config."""
    async with get_db_session() as db:
        row = await db.execute(text("SELECT enabled FROM scheduled_fetch_config LIMIT 1"))
        result = row.scalar()
        return bool(result) if result is not None else True


async def load_gsheet_stocks():
    """
    Load stock list from Google Sheet.
    Returns pandas DataFrame with columns: SYMBOL, EXCHANGE, etc.
    """
    import pandas as pd

    try:
        from gsheet_stock_get import GSheetStockClient
        client = GSheetStockClient()
        df = await asyncio.to_thread(client.get_stocks_df)
        return df
    except Exception as e:
        logger.error(f"Failed to load GSheet: {e}")
        return pd.DataFrame()


async def fetch_quotes_batched(
    stocks_df,
    requests_per_minute: int = 190,
) -> Dict[str, float]:
    """
    Fetch quotes for all stocks in batches with rate limiting.
    Uses Kotak Neo API (or configured broker API).
    Returns dict of {symbol: price}.
    """
    import pandas as pd

    if stocks_df.empty:
        return {}

    symbols = stocks_df["SYMBOL"].tolist() if "SYMBOL" in stocks_df.columns else []
    if not symbols:
        return {}

    results = {}
    batch_size = min(requests_per_minute, 50)
    delay = 60.0 / requests_per_minute

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        batch_results = await _fetch_batch(batch)
        results.update(batch_results)

        if i + batch_size < len(symbols):
            await asyncio.sleep(delay * batch_size)

    logger.info(f"Fetched quotes: {len(results)}/{len(symbols)}")
    return results


async def _fetch_batch(symbols: List[str]) -> Dict[str, float]:
    """Fetch a batch of quotes from broker API."""
    results = {}
    for symbol in symbols:
        price = await get_single_quote(symbol)
        if price is not None:
            results[symbol] = price
    return results


async def get_single_quote(symbol: str, exchange: str = "NSE") -> Optional[float]:
    """
    Fetch current market price for a single stock.
    Uses Kotak Neo API endpoint.
    """
    try:
        # Get token for symbol from stocks table
        async with get_db_session() as db:
            token_col = "nse_token" if exchange == "NSE" else "bse_token"
            row = await db.execute(text(
                f"SELECT {token_col} FROM stocks WHERE symbol = :sym LIMIT 1"
            ), {"sym": symbol})
            token = row.scalar()

        if not token:
            return None

        # Kotak Neo quote API call
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://lapi.kotaksecurities.com/scripmaster/1.1/masterscrip/token",
                params={"token": token},
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},  # placeholder
            )
            if resp.status_code == 200:
                data = resp.json()
                return float(data.get("close_price", 0)) or None
    except Exception as e:
        logger.debug(f"Quote fetch failed for {symbol}: {e}")
    return None


async def update_gsheet_with_prices(stocks_df, quotes: Dict[str, float]):
    """Update Google Sheet with fetched prices."""
    try:
        from gsheet_stock_get import GSheetStockClient
        client = GSheetStockClient()

        for symbol, price in quotes.items():
            mask = stocks_df["SYMBOL"] == symbol
            if mask.any():
                idx = stocks_df.index[mask][0]
                stocks_df.at[idx, "OPEN PRICE"] = price

        await asyncio.to_thread(client.update_sheet, stocks_df)
        logger.info(f"GSheet updated with {len(quotes)} prices")
    except Exception as e:
        logger.error(f"GSheet update failed: {e}")
