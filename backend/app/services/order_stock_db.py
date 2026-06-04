"""
Postgres-backed order stock service.
Replaces Google Sheet place_order_v2 tab when ORDER_DATA_SOURCE=postgres.

STOCK_NAME and EXCHANGE_TOKEN are stored directly in order_stocks
(synced from Kotak master scrip via master_scrip_sync.py).
Falls back to stocks table JOIN only if stored values are NULL.
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import pandas as pd
from sqlalchemy import text

from ..database import get_db_session

logger = logging.getLogger(__name__)

# Matches the column order the GSheet CSV returns so the rest of the pipeline
# (get_quote.py, place_order.py) works without changes.
_DF_COLUMNS = [
    "OK", "STOCK_NAME", "EXCHANGE_TOKEN", "GAP", "MARKET",
    "QUANTITY", "OPEN PRICE", "BUY ORDER", "SELL ORDER",
]


async def get_order_stocks_df() -> Optional[pd.DataFrame]:
    """
    Load active order stocks from Postgres.
    Uses stored stock_name/exchange_token (from Kotak master scrip sync).
    Falls back to stocks table JOIN if stored values are NULL.

    Returns a DataFrame with the same columns as the Google Sheet export.
    """
    query = text("""
        SELECT
            os.symbol       AS "OK",
            COALESCE(os.stock_name, s.nse_symbol || '-' || s.nse_series, os.symbol) AS "STOCK_NAME",
            COALESCE(os.exchange_token, s.nse_token, 0) AS "EXCHANGE_TOKEN",
            os.gap          AS "GAP",
            os.market       AS "MARKET",
            os.quantity     AS "QUANTITY",
            os.open_price   AS "OPEN PRICE",
            os.buy_order    AS "BUY ORDER",
            os.sell_order   AS "SELL ORDER"
        FROM order_stocks os
        LEFT JOIN stocks s ON s.symbol = os.symbol
        WHERE os.is_active = true
        ORDER BY os.id
    """)
    try:
        async with get_db_session() as db:
            result = await db.execute(query)
            rows = result.mappings().all()

        if not rows:
            logger.info("order_stocks table is empty")
            return pd.DataFrame(columns=_DF_COLUMNS)

        df = pd.DataFrame([dict(r) for r in rows], columns=_DF_COLUMNS)
        df["GAP"] = pd.to_numeric(df["GAP"], errors="coerce")
        df["EXCHANGE_TOKEN"] = pd.to_numeric(df["EXCHANGE_TOKEN"], errors="coerce").fillna(0).astype(int)
        df["QUANTITY"] = pd.to_numeric(df["QUANTITY"], errors="coerce").fillna(1).astype(int)
        df["OPEN PRICE"] = pd.to_numeric(df["OPEN PRICE"], errors="coerce")
        df["BUY ORDER"] = pd.to_numeric(df["BUY ORDER"], errors="coerce")
        df["SELL ORDER"] = pd.to_numeric(df["SELL ORDER"], errors="coerce")

        logger.info(f"Loaded {len(df)} order stocks from Postgres")
        return df
    except Exception as e:
        logger.exception(f"Error loading order stocks: {e}")
        return None


async def save_order_stock_prices(df: pd.DataFrame) -> bool:
    """
    Write OPEN PRICE, BUY ORDER, SELL ORDER back to order_stocks table.
    Replaces write_quote_ohlc_to_gsheet for Postgres mode.
    """
    try:
        now = datetime.now(timezone.utc)
        updates = []
        for _, row in df.iterrows():
            symbol = row.get("OK")
            open_price = row.get("OPEN PRICE")
            buy_order = row.get("BUY ORDER")
            sell_order = row.get("SELL ORDER")
            if symbol and pd.notna(open_price):
                updates.append({
                    "sym": str(symbol),
                    "op": float(open_price) if pd.notna(open_price) else None,
                    "bo": float(buy_order) if pd.notna(buy_order) else None,
                    "so": float(sell_order) if pd.notna(sell_order) else None,
                    "ts": now,
                })

        if not updates:
            logger.warning("No prices to save")
            return False

        async with get_db_session() as db:
            for u in updates:
                await db.execute(text("""
                    UPDATE order_stocks
                    SET open_price = :op, buy_order = :bo, sell_order = :so, updated_at = :ts
                    WHERE symbol = :sym
                """), u)

        logger.info(f"Saved prices for {len(updates)} order stocks to Postgres")
        return True
    except Exception as e:
        logger.exception(f"Error saving order stock prices: {e}")
        return False


async def bulk_import_stocks(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Upsert rows into order_stocks table.
    Each row must have at least 'symbol'. Optional: gap, market, quantity, stock_name, exchange_token.
    """
    inserted = 0
    updated = 0
    errors = []

    try:
        async with get_db_session() as db:
            for r in rows:
                symbol = str(r.get("symbol", r.get("OK", ""))).strip().upper()
                if not symbol:
                    continue

                gap = float(r.get("gap", r.get("GAP", 3)))
                market = str(r.get("market", r.get("MARKET", "nse_cm")))
                quantity = int(float(r.get("quantity", r.get("QUANTITY", 1))))
                stock_name = r.get("stock_name", r.get("STOCK_NAME"))
                exchange_token = r.get("exchange_token", r.get("EXCHANGE_TOKEN"))

                if stock_name and str(stock_name).strip():
                    stock_name = str(stock_name).strip()
                else:
                    stock_name = None
                if exchange_token is not None and not pd.isna(exchange_token):
                    try:
                        exchange_token = int(float(exchange_token))
                    except (ValueError, TypeError):
                        exchange_token = None
                else:
                    exchange_token = None

                try:
                    result = await db.execute(text("""
                        INSERT INTO order_stocks (symbol, gap, market, quantity, stock_name, exchange_token)
                        VALUES (:sym, :gap, :mkt, :qty, :sn, :et)
                        ON CONFLICT (symbol) DO UPDATE SET
                            gap = EXCLUDED.gap,
                            market = EXCLUDED.market,
                            quantity = EXCLUDED.quantity,
                            stock_name = COALESCE(EXCLUDED.stock_name, order_stocks.stock_name),
                            exchange_token = COALESCE(EXCLUDED.exchange_token, order_stocks.exchange_token),
                            is_active = true,
                            updated_at = now()
                        RETURNING (xmax = 0) AS is_insert
                    """), {"sym": symbol, "gap": gap, "mkt": market, "qty": quantity, "sn": stock_name, "et": exchange_token})
                    is_insert = result.scalar()
                    if is_insert:
                        inserted += 1
                    else:
                        updated += 1
                except Exception as row_err:
                    errors.append(f"{symbol}: {str(row_err)}")

        return {
            "success": True,
            "inserted": inserted,
            "updated": updated,
            "errors": errors[:20],
            "total_processed": inserted + updated,
        }
    except Exception as e:
        logger.exception(f"Bulk import error: {e}")
        return {"success": False, "message": str(e), "inserted": 0, "updated": 0, "errors": [str(e)]}


async def delete_order_stock(symbol: str) -> bool:
    """Deactivate an order stock (soft delete)."""
    try:
        async with get_db_session() as db:
            await db.execute(text(
                "UPDATE order_stocks SET is_active = false WHERE symbol = :sym"
            ), {"sym": symbol.upper()})
        return True
    except Exception as e:
        logger.exception(f"Error deleting order stock {symbol}: {e}")
        return False
