"""
Fetch Kotak master scrip CSVs (nse_cm, bse_cm) and sync exchange tokens
into the order_stocks table.

Flow:
  1. Use active Kotak session (base_url + access_token)
  2. GET /script-details/1.0/masterscrip/file-paths → CSV download URLs
  3. Download nse_cm-v1.csv → filter pGroup='EQ' → build {symbol: (stock_name, token)} map
  4. Download bse_cm-v1.csv → filter pGroup IN ('A','B') → fallback map
  5. UPDATE order_stocks SET stock_name, exchange_token for all matching symbols
     Priority: NSE EQ first, BSE A/B for anything still missing
"""

import io
import logging
from typing import Dict, Tuple, Optional

import httpx
import pandas as pd
from sqlalchemy import text

from ..database import get_db_session

logger = logging.getLogger(__name__)


async def _get_session_auth() -> Optional[Dict]:
    """Get base_url + access_token from active Kotak session."""
    from neo_login.session_manager import KotakSessionManager
    sm = KotakSessionManager()
    session_data = await sm.load_session()
    if not session_data:
        return None
    base_url = session_data.get("base_url")
    access_token = session_data.get("access_token")
    if not base_url or not access_token:
        return None
    return {"base_url": base_url, "access_token": access_token}


async def _fetch_csv_urls(base_url: str, access_token: str) -> Dict[str, Optional[str]]:
    """Fetch master scrip file paths from Kotak API."""
    url = f"{base_url}/script-details/1.0/masterscrip/file-paths"
    headers = {"accept": "*/*", "Authorization": access_token}

    async with httpx.AsyncClient(verify=False, timeout=60, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.error(f"Master scrip file-paths failed: HTTP {resp.status_code}")
            return {"nse": None, "bse": None}

        paths = resp.json().get("data", {}).get("filesPaths", [])

    nse_url = None
    bse_url = None
    for p in paths:
        if "nse_cm-v1.csv" in p:
            nse_url = p
        if "bse_cm-v1.csv" in p:
            bse_url = p

    return {"nse": nse_url, "bse": bse_url}


def _parse_nse_csv(csv_text: str) -> Dict[str, Tuple[str, int]]:
    """
    Parse NSE CM CSV → {SYMBOL: (pSymbolName, pSymbol)}
    Kotak columns: pSymbolName='ACC-EQ', pSymbol=22, pGroup='EQ'
    """
    df = pd.read_csv(io.StringIO(csv_text))
    df.columns = [c.strip() for c in df.columns]

    if "pGroup" in df.columns:
        df = df[df["pGroup"] == "EQ"].copy()

    result: Dict[str, Tuple[str, int]] = {}
    for _, row in df.iterrows():
        sym_name = str(row.get("pSymbolName", "")).strip()
        token = row.get("pSymbol")
        if not sym_name or pd.isna(token):
            continue
        clean_sym = sym_name.split("-")[0].strip().upper()
        try:
            result[clean_sym] = (sym_name, int(float(token)))
        except (ValueError, TypeError):
            continue

    logger.info(f"Parsed {len(result)} NSE EQ symbols from master scrip")
    return result


def _parse_bse_csv(csv_text: str) -> Dict[str, Tuple[str, int]]:
    """
    Parse BSE CM CSV → {SYMBOL: (pSymbolName, pSymbol)}
    Filter pGroup IN ('A', 'B') only.
    """
    df = pd.read_csv(io.StringIO(csv_text))
    df.columns = [c.strip() for c in df.columns]

    if "pGroup" in df.columns:
        df = df[df["pGroup"].isin(["A", "B"])].copy()

    result: Dict[str, Tuple[str, int]] = {}
    for _, row in df.iterrows():
        sym_name = str(row.get("pSymbolName", "")).strip()
        trd_sym = str(row.get("pTrdSymbol", "")).strip()
        token = row.get("pSymbol")
        if not sym_name or pd.isna(token):
            continue
        clean_sym = sym_name.split("-")[0].strip().upper()
        clean_trd = trd_sym.split("-")[0].strip().upper() if trd_sym else ""
        try:
            tok = int(float(token))
            result[clean_sym] = (sym_name, tok)
            if clean_trd and clean_trd != clean_sym:
                result[clean_trd] = (trd_sym, tok)
        except (ValueError, TypeError):
            continue

    logger.info(f"Parsed {len(result)} BSE A/B symbols from master scrip")
    return result


async def sync_master_scrip_to_order_stocks() -> Dict:
    """
    Main entry: fetch Kotak master scrip CSVs and update order_stocks table.
    Returns summary dict.
    """
    auth = await _get_session_auth()
    if not auth:
        return {"success": False, "message": "No active Kotak session. Authenticate with TOTP first."}

    urls = await _fetch_csv_urls(auth["base_url"], auth["access_token"])
    if not urls["nse"] and not urls["bse"]:
        return {"success": False, "message": "Failed to fetch master scrip file paths from Kotak API"}

    nse_map: Dict[str, Tuple[str, int]] = {}
    bse_map: Dict[str, Tuple[str, int]] = {}

    async with httpx.AsyncClient(verify=False, timeout=120, follow_redirects=True) as client:
        if urls["nse"]:
            logger.info(f"Downloading NSE CM master scrip...")
            resp = await client.get(urls["nse"])
            if resp.status_code == 200:
                nse_map = _parse_nse_csv(resp.text)
            else:
                logger.error(f"NSE CM download failed: HTTP {resp.status_code}")

        if urls["bse"]:
            logger.info(f"Downloading BSE CM master scrip...")
            resp = await client.get(urls["bse"])
            if resp.status_code == 200:
                bse_map = _parse_bse_csv(resp.text)
            else:
                logger.error(f"BSE CM download failed: HTTP {resp.status_code}")

    if not nse_map and not bse_map:
        return {"success": False, "message": "Failed to download any master scrip CSV"}

    # Update order_stocks: NSE first, BSE fallback
    nse_updated = 0
    bse_updated = 0
    still_missing = 0

    async with get_db_session() as db:
        rows = await db.execute(text(
            "SELECT symbol FROM order_stocks WHERE is_active = true"
        ))
        symbols = [r[0] for r in rows.fetchall()]

        for sym in symbols:
            if sym in nse_map:
                stock_name, token = nse_map[sym]
                await db.execute(text("""
                    UPDATE order_stocks
                    SET stock_name = :sn, exchange_token = :et, updated_at = now()
                    WHERE symbol = :sym
                """), {"sn": stock_name, "et": token, "sym": sym})
                nse_updated += 1
            elif sym in bse_map:
                stock_name, token = bse_map[sym]
                await db.execute(text("""
                    UPDATE order_stocks
                    SET stock_name = :sn, exchange_token = :et, updated_at = now()
                    WHERE symbol = :sym
                """), {"sn": stock_name, "et": token, "sym": sym})
                bse_updated += 1
            else:
                still_missing += 1

    total = nse_updated + bse_updated
    logger.info(
        f"Master scrip sync done: {total}/{len(symbols)} updated "
        f"(NSE={nse_updated}, BSE={bse_updated}), {still_missing} still missing"
    )

    return {
        "success": True,
        "message": f"Synced {total}/{len(symbols)} stocks (NSE={nse_updated}, BSE fallback={bse_updated}, missing={still_missing})",
        "nse_updated": nse_updated,
        "bse_updated": bse_updated,
        "still_missing": still_missing,
        "total_symbols": len(symbols),
        "nse_master_count": len(nse_map),
        "bse_master_count": len(bse_map),
    }
