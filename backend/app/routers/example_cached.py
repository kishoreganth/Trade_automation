"""
Example: How to use caching in API routes.
This file shows the pattern — will be applied to all routes during migration.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..database import get_db
from ..cache import cached, cache_get, cache_set
from ..cache_keys import PE_PENDING, invalidate_pe_analysis

router = APIRouter(prefix="/api", tags=["example"])


# Pattern 1: @cached decorator (simplest — auto cache key from args)
@router.get("/pe_analysis")
@cached("pe:pending", ttl=15)
async def get_pe_analysis(
    page: int = 1,
    per_page: int = 50,
    valuation_filter: str = "pending",
):
    """
    The @cached decorator handles:
    - Check Redis for existing result -> return immediately if hit
    - On miss: execute function, store result in Redis with 15s TTL
    - Key is auto-generated from function args
    """
    # ... actual DB query here ...
    pass


# Pattern 2: Manual cache (when you need custom invalidation logic)
@router.get("/messages/stats")
async def get_message_stats(db: AsyncSession = Depends(get_db)):
    cache_key = "messages:stats"
    result = await cache_get(cache_key)
    if result:
        return result

    row = await db.execute(text("SELECT COUNT(*) as total FROM messages"))
    stats = {"total": row.scalar()}
    await cache_set(cache_key, stats, ttl=10)
    return stats


# Pattern 3: Write endpoint that invalidates cache
@router.delete("/pe_analysis/{symbol}")
async def delete_pe_analysis(symbol: str, db: AsyncSession = Depends(get_db)):
    await db.execute(
        text("DELETE FROM quarterly_results WHERE stock_symbol = :s"),
        {"s": symbol},
    )
    await db.commit()
    await invalidate_pe_analysis()
    return {"success": True}
