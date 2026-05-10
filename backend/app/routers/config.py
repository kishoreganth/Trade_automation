"""
Configuration router — scheduled fetch config, PE formulas, sector formulas.
Extracted from: nse_url_test.py (scheduled_fetch_config CRUD, pe_formulas, sector_formulas)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..database import get_db
from ..cache import cache_delete

router = APIRouter(prefix="/api/config", tags=["config"])


# ─── Scheduled Fetch Config ───

@router.get("/scheduled_fetch")
async def get_scheduled_fetch_config(db: AsyncSession = Depends(get_db)):
    """Get current scheduled fetch configuration."""
    row = await db.execute(text("SELECT * FROM scheduled_fetch_config LIMIT 1"))
    config = row.fetchone()
    if not config:
        return {"enabled": True, "hour": 12, "minute": 40, "second": 0, "weekdays_only": True}
    return dict(config._mapping)


@router.put("/scheduled_fetch")
async def update_scheduled_fetch_config(body: dict, db: AsyncSession = Depends(get_db)):
    """Update scheduled fetch configuration."""
    await db.execute(text("""
        UPDATE scheduled_fetch_config
        SET enabled = :enabled, hour = :hour, minute = :minute, second = :second,
            weekdays_only = :weekdays, updated_at = NOW()
        WHERE id = (SELECT id FROM scheduled_fetch_config LIMIT 1)
    """), {
        "enabled": body.get("enabled", True),
        "hour": body.get("hour", 12),
        "minute": body.get("minute", 40),
        "second": body.get("second", 0),
        "weekdays": body.get("weekdays_only", True),
    })
    await db.commit()
    return {"success": True}


# ─── PE Formulas ───

@router.get("/pe_formulas")
async def get_pe_formulas(db: AsyncSession = Depends(get_db)):
    """Get all PE estimation formulas."""
    rows = await db.execute(text("SELECT * FROM pe_formulas ORDER BY is_default DESC, name"))
    return {"formulas": [dict(r._mapping) for r in rows.fetchall()]}


@router.put("/pe_formulas/{formula_id}")
async def update_pe_formula(formula_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    """Update a PE formula."""
    await db.execute(text("""
        UPDATE pe_formulas
        SET q1_expr = :q1, q2_expr = :q2, q3_expr = :q3, q4_expr = :q4, updated_at = NOW()
        WHERE id = :id
    """), {
        "id": formula_id,
        "q1": body.get("q1_expr", "Q1*4"),
        "q2": body.get("q2_expr", "(Q1+Q2)*2"),
        "q3": body.get("q3_expr", "(Q1+Q2+Q3)*4/3"),
        "q4": body.get("q4_expr", "FY"),
    })
    await db.commit()
    await cache_delete("pe:*")
    return {"success": True}


# ─── Sector Formulas ───

@router.get("/sector_formulas")
async def get_sector_formulas(db: AsyncSession = Depends(get_db)):
    """Get all sector-specific formula overrides."""
    rows = await db.execute(text("SELECT * FROM sector_formulas ORDER BY sector, quarter"))
    return {"formulas": [dict(r._mapping) for r in rows.fetchall()]}


@router.post("/sector_formulas")
async def create_sector_formula(body: dict, db: AsyncSession = Depends(get_db)):
    """Create or update sector formula override."""
    await db.execute(text("""
        INSERT INTO sector_formulas (sector, sub_sector, quarter, formula_expr, created_at, updated_at)
        VALUES (:sector, :sub, :q, :expr, NOW(), NOW())
        ON CONFLICT (sector, sub_sector, quarter)
        DO UPDATE SET formula_expr = EXCLUDED.formula_expr, updated_at = NOW()
    """), {
        "sector": body["sector"],
        "sub": body.get("sub_sector", ""),
        "q": body["quarter"],
        "expr": body["formula_expr"],
    })
    await db.commit()
    return {"success": True}
