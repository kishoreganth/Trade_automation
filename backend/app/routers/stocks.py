"""
Stocks & Scrip Master router.
Extracted from: nse_url_test.py (/api/refresh_scrip_master, stocks management)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..database import get_db
from ..cache import cached
from ..cache_keys import invalidate_stocks

router = APIRouter(prefix="/api", tags=["stocks"])


@router.get("/stocks")
@cached("stocks:list", ttl=60)
async def get_stocks(db: AsyncSession = Depends(get_db)):
    """Get all active stocks."""
    rows = await db.execute(text(
        "SELECT id, symbol, company_name, exchange, sector, sub_sector, nse_token, bse_token, isin "
        "FROM stocks WHERE is_active = true ORDER BY symbol"
    ))
    return {"stocks": [dict(r._mapping) for r in rows.fetchall()]}


@router.post("/refresh_scrip_master")
async def refresh_scrip_master(db: AsyncSession = Depends(get_db)):
    """
    Refresh NSE + BSE scrip master data.
    Updates tokens, adds new stocks, marks delisted as inactive.
    TODO: wire up _fetch_nse_token_map / _fetch_bse_token_map from services.
    """
    nse_count = 0
    bse_count = 0

    try:
        await invalidate_stocks()
        return {"success": True, "nse_count": nse_count, "bse_count": bse_count}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/stocks/{symbol}")
async def get_stock_detail(symbol: str, db: AsyncSession = Depends(get_db)):
    """Get stock details + all quarterly results."""
    stock = await db.execute(text(
        "SELECT * FROM stocks WHERE symbol = :sym"
    ), {"sym": symbol})
    stock_row = stock.fetchone()

    quarters = await db.execute(text(
        "SELECT * FROM quarterly_results WHERE stock_symbol = :sym ORDER BY financial_year DESC, quarter DESC"
    ), {"sym": symbol})

    return {
        "stock": dict(stock_row._mapping) if stock_row else None,
        "quarterly_results": [dict(r._mapping) for r in quarters.fetchall()],
    }
