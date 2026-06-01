"""PE Audit Log service — fire-and-forget recording of all PE review actions."""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def log_pe_action(
    db: AsyncSession,
    stock_symbol: str,
    row_id: Optional[int],
    action: str,
    old_valuation: Optional[str] = None,
    new_valuation: Optional[str] = None,
    old_fields: Optional[dict] = None,
    new_fields: Optional[dict] = None,
    outcome: str = "success",
    error_detail: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """Insert an audit log row. Never raises — failures are logged to stderr."""
    try:
        await db.execute(text("""
            INSERT INTO pe_audit_log
                (stock_symbol, row_id, action, old_valuation, new_valuation,
                 old_fields, new_fields, outcome, error_detail, request_id)
            VALUES
                (:stock_symbol, :row_id, :action, :old_valuation, :new_valuation,
                 CAST(:old_fields AS jsonb), CAST(:new_fields AS jsonb),
                 :outcome, :error_detail, :request_id)
        """), {
            "stock_symbol": stock_symbol,
            "row_id": row_id,
            "action": action,
            "old_valuation": old_valuation or None,
            "new_valuation": new_valuation or None,
            "old_fields": _safe_json(old_fields),
            "new_fields": _safe_json(new_fields),
            "outcome": outcome,
            "error_detail": error_detail,
            "request_id": request_id,
        })
        await db.commit()
    except Exception:
        logger.exception("Failed to write PE audit log for %s (action=%s)", stock_symbol, action)
        try:
            await db.rollback()
        except Exception:
            pass


def _safe_json(obj: Optional[dict]) -> Optional[str]:
    """Serialize dict to JSON string for CAST, or None."""
    if obj is None:
        return None
    import json
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return None
