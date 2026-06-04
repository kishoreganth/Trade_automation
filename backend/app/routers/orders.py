"""
Place Order router — Full implementation.
Endpoints: sheet data, session status, TOTP auth, get quotes, place all orders.
Supports ENV toggle: ORDER_DATA_SOURCE=gsheet (default) or ORDER_DATA_SOURCE=postgres
"""

import asyncio
import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

# Fix Windows stdout encoding for emoji characters in neo_main_login prints
import io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Project root: backend/app/routers/orders.py → go 3 levels up
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOTENV_PATH = PROJECT_ROOT / ".env"
BACKEND_DOTENV = Path(__file__).resolve().parents[2] / ".env"

# Add backend/app/services to path for imports (gsheet_stock_get, place_order, neo_main_login, neo_login)
SERVICES_DIR = Path(__file__).resolve().parents[1] / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

# Load .env — project root first, then backend/.env overrides
from dotenv import load_dotenv
load_dotenv(DOTENV_PATH, override=True)
load_dotenv(BACKEND_DOTENV, override=True)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/place_order", tags=["orders"])


def _order_source() -> str:
    """Return 'postgres' or 'gsheet' based on ORDER_DATA_SOURCE env."""
    return (_get_env("ORDER_DATA_SOURCE") or "gsheet").strip().lower()


class TOTPRequest(BaseModel):
    totp: str


class PlaceOrdersRequest(BaseModel):
    orders_per_minute: int = 185
    max_concurrent: int = 2


class ImportStocksRequest(BaseModel):
    stocks: List[dict]


def _get_env(key: str) -> Optional[str]:
    """Get env var, stripping quotes if present."""
    val = os.getenv(key)
    if val and val.startswith('"') and val.endswith('"'):
        val = val[1:-1]
    return val


def _sanitize_df_rows(df):
    """Replace NaN/inf with None for JSON serialization."""
    import pandas as pd
    import numpy as np
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.where(pd.notna(df), None)
    rows = df.to_dict(orient="records")
    for row in rows:
        for k, v in row.items():
            if isinstance(v, float) and (v != v or v == float('inf') or v == float('-inf')):
                row[k] = None
    return rows


# ─── Data Source ───

@router.get("/source")
async def get_order_source():
    """Return current data source (gsheet or postgres)."""
    return {"source": _order_source()}


# ─── Sheet Data ───

@router.get("/sheet")
async def get_order_sheet():
    """Load order data from Google Sheet or Postgres based on ORDER_DATA_SOURCE."""
    source = _order_source()

    if source == "postgres":
        return await _get_order_sheet_postgres()
    return await _get_order_sheet_gsheet()


async def _get_order_sheet_postgres():
    """Load order stock data from Postgres (order_stocks JOIN stocks)."""
    try:
        from ..services.order_stock_db import get_order_stocks_df

        df = await get_order_stocks_df()
        if df is None:
            return {"rows": [], "error": "Failed to load from Postgres"}
        if df.empty:
            return {"rows": [], "error": "No order stocks configured. Import stocks first."}

        rows = _sanitize_df_rows(df)
        return {"rows": rows, "total": len(rows), "source": "postgres", "sheet_url": ""}
    except Exception as e:
        logger.exception(f"Error loading order stocks from Postgres: {e}")
        return {"rows": [], "error": str(e)}


async def _get_order_sheet_gsheet():
    """Load order sheet data from Google Sheet (PLACE_ORDER_V2 tab) — original logic."""
    try:
        import pandas as pd
        from gsheet_stock_get import GSheetStockClient

        base_url = _get_env("BASE_SHEET_URL")
        gid = _get_env("sheet_gid")
        sheet_id = _get_env("sheet_id")

        if not base_url or not gid:
            logger.error(f"Missing env vars: BASE_SHEET_URL={base_url}, sheet_gid={gid}")
            return {"rows": [], "error": "Server config error: Missing BASE_SHEET_URL or sheet_gid in .env"}

        sheet_url = f"{base_url}{gid}"
        logger.info(f"Fetching sheet from: {sheet_url[:80]}...")

        client = GSheetStockClient()
        df = await client.get_stock_dataframe(sheet_url)

        if df is None:
            return {"rows": [], "error": "Failed to fetch Google Sheet (network error or sheet not public)"}
        if df.empty:
            return {"rows": [], "error": "Google Sheet is empty"}

        rows = _sanitize_df_rows(df)
        return {
            "rows": rows,
            "total": len(rows),
            "source": "gsheet",
            "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={gid}" if sheet_id else ""
        }
    except Exception as e:
        logger.exception(f"Error loading sheet: {e}")
        return {"rows": [], "error": str(e)}


# ─── Session Status ───

@router.get("/session/status")
async def get_session_status():
    """Check if Kotak session is active and valid."""
    try:
        from neo_login.session_manager import KotakSessionManager
        session_manager = KotakSessionManager()
        session_data = await session_manager.load_session()

        if not session_data:
            return {"active": False, "message": "No session found", "expires_at": None}

        expires_at = session_data.get("expires_at")
        if expires_at:
            exp_dt = datetime.fromisoformat(expires_at)
            if datetime.now() > exp_dt:
                return {"active": False, "message": "Session expired", "expires_at": expires_at}

        # Session file exists and not expired — treat as active.
        # Only mark inactive on explicit 401 (unauthorized).
        # Non-401 errors (424, 500, timeout) are transient — session is still valid.
        is_valid = await session_manager.validate_session(session_data)

        # If validation returns False but session isn't expired, check if it was a hard 401
        # vs a transient error. Session manager clears file on 401, so if file still exists → active.
        if not is_valid:
            recheck = await session_manager.load_session()
            if recheck:
                # Session file still exists (not cleared by 401) → transient error, treat as active
                return {
                    "active": True,
                    "message": "Session active",
                    "expires_at": expires_at,
                    "sid": session_data.get("sid", "")[:8] + "..." if session_data.get("sid") else None,
                    "created_at": session_data.get("created_at")
                }

        return {
            "active": is_valid,
            "message": "Session active" if is_valid else "Session invalid (unauthorized)",
            "expires_at": expires_at,
            "sid": session_data.get("sid", "")[:8] + "..." if session_data.get("sid") else None,
            "created_at": session_data.get("created_at")
        }
    except Exception as e:
        logger.exception(f"Error checking session: {e}")
        return {"active": False, "message": str(e), "expires_at": None}


# ─── TOTP Authentication ───

@router.post("/session/authenticate")
async def authenticate_with_totp(body: TOTPRequest):
    """Authenticate with TOTP code to create/refresh Kotak session."""
    try:
        mobile_number = _get_env("MOBILE_NUMBER")
        ucc = _get_env("UCC")
        mpin = _get_env("MPIN")
        access_token = _get_env("NEO_ACCESS_TOKEN")

        missing = []
        if not mobile_number: missing.append("MOBILE_NUMBER")
        if not ucc: missing.append("UCC")
        if not mpin: missing.append("MPIN")
        if not access_token: missing.append("NEO_ACCESS_TOKEN")

        if missing:
            msg = f"Missing server credentials in .env: {', '.join(missing)}"
            logger.error(msg)
            return {"success": False, "message": msg}

        logger.info(f"TOTP auth attempt: mobile={mobile_number}, ucc={ucc}, totp={body.totp[:2]}****")

        from neo_main_login import main as neo_main_login
        session_data = await neo_main_login(mobile_number, ucc, body.totp, mpin, access_token)

        if not session_data:
            return {"success": False, "message": "Authentication failed. Check TOTP code and try again."}

        from neo_login.session_manager import KotakSessionManager
        session_manager = KotakSessionManager()
        loaded = await session_manager.load_session()
        expires_at = loaded.get("expires_at") if loaded else None

        return {
            "success": True,
            "message": "Session authenticated successfully",
            "expires_at": expires_at
        }
    except Exception as e:
        logger.exception(f"Authentication error: {e}")
        return {"success": False, "message": f"Authentication error: {str(e)}"}


# ─── Get Quotes ───

@router.post("/quotes/fetch")
async def fetch_quotes():
    """Fetch live quotes for all stocks, update storage with OPEN PRICE, BUY/SELL ORDER."""
    source = _order_source()
    if source == "postgres":
        return await _fetch_quotes_postgres()
    return await _fetch_quotes_gsheet()


async def _fetch_quotes_postgres():
    """Fetch quotes using Postgres as the data source."""
    try:
        from get_quote import (
            get_gsheet_stocks_df,
            get_symbol_from_gsheet_stocks_df,
            get_quotes_with_rate_limit,
            flatten_quote_result_list,
            fetch_ohlc_from_quote_result,
            update_df_with_quote_ohlc,
        )
        from ..services.order_stock_db import get_order_stocks_df, save_order_stock_prices

        df = await get_order_stocks_df()
        if df is None or df.empty:
            return {"success": False, "message": "No order stocks in Postgres. Import stocks first.", "rows": []}

        all_rows = await get_gsheet_stocks_df(df)
        symbols_list, valid_indices = await get_symbol_from_gsheet_stocks_df(all_rows)

        if not symbols_list:
            return {"success": False, "message": "No valid symbols found", "rows": []}

        batch_size = 190
        symbol_batches = [symbols_list[i:i + batch_size] for i in range(0, len(symbols_list), batch_size)]
        quote_result = await get_quotes_with_rate_limit(symbol_batches, requests_per_minute=190)

        flattened = await flatten_quote_result_list(quote_result)
        quote_ohlc = await fetch_ohlc_from_quote_result(flattened)
        df = await update_df_with_quote_ohlc(df, quote_ohlc, valid_indices)

        write_success = await save_order_stock_prices(df)

        rows = _sanitize_df_rows(df)
        fetch_time = datetime.now().strftime("%I:%M %p")

        return {
            "success": True,
            "message": f"Fetched quotes for {len(symbols_list)} stocks",
            "rows": rows,
            "total": len(rows),
            "fetch_time": fetch_time,
            "sheet_updated": write_success,
            "source": "postgres",
            "stats": {
                "total_symbols": len(symbols_list),
                "quotes_received": len(quote_ohlc),
                "prices_mapped": sum(1 for r in rows if r.get("OPEN PRICE") and r["OPEN PRICE"] > 0)
            }
        }
    except Exception as e:
        logger.exception(f"Error fetching quotes (postgres): {e}")
        return {"success": False, "message": str(e), "rows": []}


async def _fetch_quotes_gsheet():
    """Fetch quotes using Google Sheet as the data source — original logic."""
    try:
        from gsheet_stock_get import GSheetStockClient
        from get_quote import (
            get_gsheet_stocks_df,
            get_symbol_from_gsheet_stocks_df,
            get_quotes_with_rate_limit,
            flatten_quote_result_list,
            fetch_ohlc_from_quote_result,
            update_df_with_quote_ohlc,
            write_quote_ohlc_to_gsheet,
        )

        base_url = _get_env("BASE_SHEET_URL")
        gid = _get_env("sheet_gid")
        sheet_id = _get_env("sheet_id")

        if not base_url or not gid:
            return {"success": False, "message": "Missing BASE_SHEET_URL or sheet_gid", "rows": []}

        sheet_url = f"{base_url}{gid}"
        client = GSheetStockClient()
        df = await client.get_stock_dataframe(sheet_url)

        if df is None or df.empty:
            return {"success": False, "message": "No data in sheet", "rows": []}

        all_rows = await get_gsheet_stocks_df(df)
        symbols_list, valid_indices = await get_symbol_from_gsheet_stocks_df(all_rows)

        if not symbols_list:
            return {"success": False, "message": "No valid symbols found", "rows": []}

        batch_size = 190
        symbol_batches = [symbols_list[i:i + batch_size] for i in range(0, len(symbols_list), batch_size)]
        quote_result = await get_quotes_with_rate_limit(symbol_batches, requests_per_minute=190)

        flattened = await flatten_quote_result_list(quote_result)
        quote_ohlc = await fetch_ohlc_from_quote_result(flattened)

        df = await update_df_with_quote_ohlc(df, quote_ohlc, valid_indices)

        write_success = await write_quote_ohlc_to_gsheet(df, sheet_id, gid)

        rows = _sanitize_df_rows(df)
        fetch_time = datetime.now().strftime("%I:%M %p")

        return {
            "success": True,
            "message": f"Fetched quotes for {len(symbols_list)} stocks",
            "rows": rows,
            "total": len(rows),
            "fetch_time": fetch_time,
            "sheet_updated": write_success,
            "source": "gsheet",
            "stats": {
                "total_symbols": len(symbols_list),
                "quotes_received": len(quote_ohlc),
                "prices_mapped": sum(1 for r in rows if r.get("OPEN PRICE") and r["OPEN PRICE"] > 0)
            }
        }
    except Exception as e:
        logger.exception(f"Error fetching quotes: {e}")
        return {"success": False, "message": str(e), "rows": []}


# ─── Place All Orders ───

@router.post("/execute/all")
async def place_all_orders(body: PlaceOrdersRequest):
    """Place BUY + SELL orders for all stocks."""
    source = _order_source()
    if source == "postgres":
        return await _place_all_orders_postgres(body)
    return await _place_all_orders_gsheet(body)


async def _place_all_orders_postgres(body: PlaceOrdersRequest):
    """Place orders using Postgres data source."""
    try:
        from get_quote import get_gsheet_stocks_df
        from place_order import get_order_data, place_orders_with_rate_limit
        from ..services.order_stock_db import get_order_stocks_df
        import pandas as pd

        df = await get_order_stocks_df()
        if df is None or df.empty:
            return {"success": False, "message": "No order stocks in Postgres", "results": []}

        all_rows = await get_gsheet_stocks_df(df)
        if not all_rows:
            return {"success": False, "message": "No rows found", "results": []}

        valid_rows = _filter_valid_order_rows(all_rows)
        if not valid_rows:
            return {"success": False, "message": f"No rows with valid BUY/SELL prices ({len(all_rows)} total rows). Fetch quotes first.", "results": []}

        all_orders = await get_order_data(valid_rows)
        logger.info(f"Placing {len(all_orders)} orders for {len(valid_rows)} stocks (postgres)...")

        results = await place_orders_with_rate_limit(
            all_orders,
            orders_per_minute=body.orders_per_minute,
            max_concurrent=body.max_concurrent
        )

        successful = sum(1 for r in results if r and not isinstance(r, Exception) and r.get("status") != "error")
        order_time = datetime.now().strftime("%I:%M %p")

        return {
            "success": True,
            "message": f"Placed {successful}/{len(results)} orders for {len(valid_rows)} stocks",
            "total_orders": len(results),
            "successful": successful,
            "failed": len(results) - successful,
            "order_time": order_time,
            "results": results[:50]
        }
    except Exception as e:
        logger.exception(f"Error placing orders (postgres): {e}")
        return {"success": False, "message": str(e), "results": []}


async def _place_all_orders_gsheet(body: PlaceOrdersRequest):
    """Place orders using Google Sheet data source — original logic."""
    try:
        from gsheet_stock_get import GSheetStockClient
        from get_quote import get_gsheet_stocks_df
        from place_order import get_order_data, place_orders_with_rate_limit

        base_url = _get_env("BASE_SHEET_URL")
        gid = _get_env("sheet_gid")

        if not base_url or not gid:
            return {"success": False, "message": "Missing BASE_SHEET_URL or sheet_gid", "results": []}

        sheet_url = f"{base_url}{gid}"
        client = GSheetStockClient()
        df = await client.get_stock_dataframe(sheet_url)

        if df is None or df.empty:
            return {"success": False, "message": "No data in sheet", "results": []}

        all_rows = await get_gsheet_stocks_df(df)
        if not all_rows:
            return {"success": False, "message": "No rows in sheet", "results": []}

        valid_rows = _filter_valid_order_rows(all_rows)
        if not valid_rows:
            return {"success": False, "message": f"No rows with valid BUY/SELL prices ({len(all_rows)} total rows). Fetch quotes first.", "results": []}

        all_orders = await get_order_data(valid_rows)
        logger.info(f"Placing {len(all_orders)} orders for {len(valid_rows)} stocks...")

        results = await place_orders_with_rate_limit(
            all_orders,
            orders_per_minute=body.orders_per_minute,
            max_concurrent=body.max_concurrent
        )

        successful = sum(1 for r in results if r and not isinstance(r, Exception) and r.get("status") != "error")
        order_time = datetime.now().strftime("%I:%M %p")

        return {
            "success": True,
            "message": f"Placed {successful}/{len(results)} orders for {len(valid_rows)} stocks",
            "total_orders": len(results),
            "successful": successful,
            "failed": len(results) - successful,
            "order_time": order_time,
            "results": results[:50]
        }
    except Exception as e:
        logger.exception(f"Error placing orders: {e}")
        return {"success": False, "message": str(e), "results": []}


def _filter_valid_order_rows(all_rows):
    """Filter rows that have valid BUY/SELL prices > 0."""
    import pandas as pd
    valid_rows = []
    for r in all_rows:
        buy = r.get("BUY ORDER")
        sell = r.get("SELL ORDER")
        try:
            buy_f = float(buy) if buy is not None and not (isinstance(buy, float) and pd.isna(buy)) else 0
            sell_f = float(sell) if sell is not None and not (isinstance(sell, float) and pd.isna(sell)) else 0
            if buy_f > 0 and sell_f > 0:
                valid_rows.append(r)
        except (ValueError, TypeError):
            continue
    return valid_rows


# ─── Single Order Execute (legacy) ───

@router.post("/execute")
async def execute_single_order(body: dict):
    """Execute a single trade order via broker API."""
    try:
        from place_order import place_order

        symbol = body.get("symbol", "")
        action = body.get("action", "")
        qty = body.get("qty", 1)
        price = body.get("price", 0)

        if not all([symbol, action, qty]):
            return {"success": False, "error": "Missing required fields"}

        qty_str = str(min(max(1, int(qty)), 2))

        order_data = {
            "am": "NO", "dq": "0", "es": "nse_cm", "mp": "0",
            "pc": "MIS", "pf": "N", "pr": str(price), "pt": "L",
            "qt": qty_str, "rt": "DAY", "tp": "0", "ts": symbol,
            "tt": "B" if action.upper() == "BUY" else "S"
        }

        result = await place_order(order_data)

        if result and result.get("status") != "error":
            return {"success": True, "order_id": result.get("nOrdNo", ""), "symbol": symbol, "action": action, "status": "submitted"}
        else:
            return {"success": False, "error": result.get("message", "Order failed") if result else "No response"}
    except Exception as e:
        logger.exception(f"Error executing order: {e}")
        return {"success": False, "error": str(e)}


# ─── Order Stocks Import (Postgres mode) ───

@router.post("/stocks/import")
async def import_order_stocks(body: ImportStocksRequest):
    """Bulk import/upsert stocks into order_stocks table (Postgres mode only)."""
    if _order_source() != "postgres":
        return {"success": False, "message": "Import only available when ORDER_DATA_SOURCE=postgres"}
    try:
        from ..services.order_stock_db import bulk_import_stocks
        result = await bulk_import_stocks(body.stocks)
        return result
    except Exception as e:
        logger.exception(f"Error importing stocks: {e}")
        return {"success": False, "message": str(e)}


@router.post("/stocks/upload")
async def upload_order_stocks_csv(file: UploadFile = File(...)):
    """Upload CSV/Excel file to import stocks into order_stocks table."""
    if _order_source() != "postgres":
        return {"success": False, "message": "Upload only available when ORDER_DATA_SOURCE=postgres"}
    try:
        import pandas as pd
        from ..services.order_stock_db import bulk_import_stocks

        content = await file.read()
        fname = (file.filename or "").lower()

        if fname.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content))

        df.columns = df.columns.str.strip()

        col_map = {}
        for col in df.columns:
            cl = col.upper()
            if cl in ("OK", "SYMBOL"):
                col_map[col] = "symbol"
            elif cl == "GAP":
                col_map[col] = "gap"
            elif cl == "MARKET":
                col_map[col] = "market"
            elif cl == "QUANTITY":
                col_map[col] = "quantity"
        df = df.rename(columns=col_map)

        if "symbol" not in df.columns:
            return {"success": False, "message": "CSV must have an 'OK' or 'SYMBOL' column"}

        rows = df.to_dict(orient="records")
        result = await bulk_import_stocks(rows)
        return result
    except Exception as e:
        logger.exception(f"Error uploading stocks: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/stocks/{symbol}")
async def remove_order_stock(symbol: str):
    """Deactivate an order stock (Postgres mode only)."""
    if _order_source() != "postgres":
        return {"success": False, "message": "Delete only available when ORDER_DATA_SOURCE=postgres"}
    try:
        from ..services.order_stock_db import delete_order_stock
        ok = await delete_order_stock(symbol)
        return {"success": ok, "symbol": symbol}
    except Exception as e:
        logger.exception(f"Error removing stock {symbol}: {e}")
        return {"success": False, "message": str(e)}


# ─── Master Scrip Sync (Kotak API → order_stocks tokens) ───

@router.post("/sync_master_scrip")
async def sync_master_scrip():
    """Fetch Kotak master scrip CSVs (nse_cm + bse_cm) and sync exchange tokens into order_stocks."""
    if _order_source() != "postgres":
        return {"success": False, "message": "Sync only available when ORDER_DATA_SOURCE=postgres"}
    try:
        from ..services.master_scrip_sync import sync_master_scrip_to_order_stocks
        result = await sync_master_scrip_to_order_stocks()
        return result
    except Exception as e:
        logger.exception(f"Error syncing master scrip: {e}")
        return {"success": False, "message": str(e)}
