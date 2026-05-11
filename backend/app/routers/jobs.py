"""
Jobs API router — trigger and monitor background tasks.
Extracted from: nse_url_test.py (job management endpoints)
"""

import uuid
from fastapi import APIRouter, HTTPException

from ..cache import publish_ws_event
from worker.tasks.quotes import fetch_quotes_manual
from worker.tasks.announcements import (
    fetch_nse_equities,
    fetch_bse_all_announcements,
    fetch_bse_results,
)
from worker.tasks.extraction import retry_stuck_extractions, run_ai_analysis

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/{job_type}/start")
async def start_job(job_type: str):
    """Trigger a background job via Celery."""
    job_id = str(uuid.uuid4())[:8]

    if job_type == "fetch_quotes":
        fetch_quotes_manual.delay(job_id=job_id)

    elif job_type == "fetch_nse":
        fetch_nse_equities.delay()

    elif job_type == "fetch_bse":
        fetch_bse_all_announcements.delay()

    elif job_type == "fetch_bse_results":
        fetch_bse_results.delay()

    elif job_type == "extraction":
        retry_stuck_extractions.delay()

    else:
        raise HTTPException(status_code=400, detail=f"Unknown job type: {job_type}")

    await publish_ws_event({
        "type": "job_progress",
        "job": {"id": job_id, "type": job_type, "status": "queued", "progress": 0},
    })

    return {"success": True, "job_id": job_id, "job_type": job_type, "status": "queued"}


@router.post("/ai_analysis/start")
async def start_ai_analysis(body: dict):
    """Trigger AI analysis for a stock."""
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")

    run_ai_analysis.delay(stock_symbol=symbol, analysis_type="valuation")

    await publish_ws_event({
        "type": "ai_analysis_status",
        "stock_symbol": symbol,
        "status": "started",
    })

    return {"success": True, "symbol": symbol, "status": "analysis_started"}
