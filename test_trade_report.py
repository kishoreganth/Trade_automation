#!/usr/bin/env python3
"""
Test script: Get daily trade report from Kotak Neo API.
Uses session from kotak_session.json (login via dashboard TOTP first).
Ref: https://github.com/Kotak-Neo/kotak-neo-api/blob/main/docs/Trade_report.md
"""
import asyncio
import aiohttp
import json
import ssl
import logging
from pathlib import Path

from neo_login.session_manager import KotakSessionManager
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_trade_report() -> dict | None:
    """
    Get trade report from Kotak Neo API.
    GET {base_url}/quick/user/trades
    Ref: https://github.com/Kotak-Neo/kotak-neo-api/blob/main/docs/Trade_report.md
    """
    session_manager = KotakSessionManager()
    session_data = await session_manager.load_session()
    if not session_data:
        logger.error("No session. Login via dashboard TOTP first, or run neo_main_login.")
        return None

    sid = session_data.get("sid")
    auth_token = session_data.get("token")
    base_url = session_data.get("base_url")
    if not all([sid, auth_token, base_url]):
        logger.error("Missing sid, token, or base_url in session")
        return None

    url = f"{base_url}/quick/user/trades"

    headers = {
        "accept": "application/json",
        "Sid": sid,
        "Auth": auth_token,
    }

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    try:
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as session:
            async with session.get(url, headers=headers) as response:
                text = await response.text()
                if response.status == 200:
                    try:
                        data = json.loads(text)
                        return data
                    except json.JSONDecodeError:
                        return {"raw": text}
                else:
                    logger.error(f"Trade report failed: {response.status} - {text}")
                    return None
    except Exception as e:
        logger.error(f"Trade report error: {e}")
        return None


def _ensure_session():
    """Ensure valid session; prompt for TOTP if needed."""
    session_file = Path("kotak_session.json")
    if session_file.exists():
        return True
    logger.warning("No kotak_session.json. Run TOTP login from dashboard first.")
    return False


async def main():
    if not _ensure_session():
        logger.info("To login: Start nse_url_test.py, go to Place Order, enter TOTP.")
        return

    logger.info("Fetching trade report from Kotak Neo API...")
    result = await get_trade_report()

    if result is None:
        logger.error("Failed to get trade report")
        return

    # Pretty print
    if "data" in result:
        trades = result["data"]
        logger.info(f"Total trades: {len(trades)}")
        for i, t in enumerate(trades[:10], 1):
            sym = t.get("trdSym", t.get("sym", "?"))
            qty = t.get("fldQty", "?")
            prc = t.get("avgPrc", "?")
            side = t.get("trnsTp", "?")  # B/S
            dt = t.get("flDt", t.get("exTm", "?"))
            print(f"  {i}. {sym} | {side} {qty} @ {prc} | {dt}")
        if len(trades) > 10:
            print(f"  ... and {len(trades) - 10} more")
    else:
        print(json.dumps(result, indent=2))

    # Optionally save to file
    out_file = Path("trade_report.json")
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved to {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
