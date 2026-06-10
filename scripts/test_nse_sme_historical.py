"""
NSE SME Historical Data Feasibility Test
==========================================
Fetches NSE SME corporate announcements from April 1, 2026 to May 30, 2026.
Counts total announcements, financial results, unique symbols.
Also checks what already exists in the DB for this period.

Purpose: Understand data volume before building full migration script.
NO DB writes -- read-only test.
"""

import asyncio
import time
import json
import pathlib
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict

import httpx
import paramiko
from typing import Optional

SCRIPT_DIR = pathlib.Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "nse_sme_historical"
OUTPUT_DIR.mkdir(exist_ok=True)

IST = timezone(timedelta(hours=5, minutes=30))

# Date range
START_DATE = datetime(2026, 4, 1)
END_DATE = datetime(2026, 5, 30)

NSE_API_URL = "https://www.nseindia.com/api/corporate-announcements"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}

# DB connection (SSH -> Docker -> Postgres)
SSH_HOST = "122.165.113.41"
SSH_USER = "kishore"
SSH_PASS = "root"
DB_CONTAINER = "trade_postgres"
DB_NAME = "automation_trade"
DB_USER = "trade_user"

# Financial result detection (same logic as nse_fetcher.py)
_EXCLUDE_SUBJECTS = (
    "clarification",
    "reply to clarification",
    "reasons for delayed",
    "non-submission",
    "newspaper",
)


def _is_financial_result(ann: dict) -> bool:
    desc = ann.get("desc", "").lower()
    detail = ann.get("attchmntText", "").lower()

    if any(ex in desc for ex in _EXCLUDE_SUBJECTS):
        return False
    if "intimation" in desc:
        return False
    if "newspaper" in detail:
        return False
    if "financial result" in desc:
        return True
    if "outcome of board meeting" in desc:
        if "financial result" in detail:
            return True
    return False


# ---------------------------------------------------------------------------
# NSE API Fetch (httpx with session)
# ---------------------------------------------------------------------------

async def fetch_nse_sme_for_date(
    client: httpx.AsyncClient, date: datetime
) -> list[dict]:
    """Fetch all NSE SME announcements for a specific date."""
    date_str = date.strftime("%d-%m-%Y")
    params = {
        "index": "sme",
        "from_date": date_str,
        "to_date": date_str,
    }
    try:
        resp = await client.get(NSE_API_URL, params=params, headers=NSE_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            return []  # Session expired, caller will retry
        raise
    except Exception as e:
        print(f"    [ERROR] {date_str}: {type(e).__name__}: {e}")
        return []


async def create_nse_session(client: httpx.AsyncClient) -> bool:
    """Hit NSE homepage to get cookies/session."""
    try:
        resp = await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# DB Check (existing data in quarterly_results for this period)
# ---------------------------------------------------------------------------

def check_db_existing(start: datetime, end: datetime) -> Optional[dict]:
    """SSH into server, check existing NSE SME data in quarterly_results."""
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=15)

        def run_sql(sql: str) -> str:
            escaped = sql.replace("'", "'\\''")
            cmd = f"docker exec {DB_CONTAINER} psql -U {DB_USER} -d {DB_NAME} -t -A -F '|' -c '{escaped}'"
            _, stdout, stderr = client.exec_command(cmd, timeout=60)
            return stdout.read().decode("utf-8", errors="replace")

        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        # Count existing NSE entries in quarterly_results for this period
        total_qr = run_sql(f"""
            SELECT COUNT(*) FROM quarterly_results
            WHERE exchange = 'NSE'
              AND announcement_date >= '{start_str}'
              AND announcement_date <= '{end_str}'
        """).strip()

        # Count NSE SME specifically (join with stocks table)
        sme_qr = run_sql(f"""
            SELECT COUNT(*) FROM quarterly_results qr
            LEFT JOIN stocks s ON s.symbol = qr.stock_symbol
            WHERE qr.exchange = 'NSE'
              AND qr.announcement_date >= '{start_str}'
              AND qr.announcement_date <= '{end_str}'
              AND COALESCE(s.nse_series, '') IN ('SM', 'ST')
        """).strip()

        # Pending vs Reviewed for NSE in this period
        pending_qr = run_sql(f"""
            SELECT COUNT(*) FROM quarterly_results
            WHERE exchange = 'NSE'
              AND announcement_date >= '{start_str}'
              AND announcement_date <= '{end_str}'
              AND (valuation IS NULL OR valuation = '')
        """).strip()

        reviewed_qr = run_sql(f"""
            SELECT COUNT(*) FROM quarterly_results
            WHERE exchange = 'NSE'
              AND announcement_date >= '{start_str}'
              AND announcement_date <= '{end_str}'
              AND valuation IS NOT NULL AND valuation != ''
        """).strip()

        # Unique symbols in this period
        unique_syms = run_sql(f"""
            SELECT COUNT(DISTINCT stock_symbol) FROM quarterly_results
            WHERE exchange = 'NSE'
              AND announcement_date >= '{start_str}'
              AND announcement_date <= '{end_str}'
        """).strip()

        # NSE SME stocks in stocks table
        sme_stocks_count = run_sql("""
            SELECT COUNT(*) FROM stocks
            WHERE nse_series IN ('SM', 'ST')
        """).strip()

        # bse_announcements_log entries for NSE in this period
        ann_log = run_sql(f"""
            SELECT COUNT(*) FROM bse_announcements_log
            WHERE exchange = 'NSE'
              AND created_at >= '{start_str}'
              AND created_at <= '{end_str}'
        """).strip()

        client.close()

        return {
            "total_qr_nse": int(total_qr) if total_qr.isdigit() else 0,
            "sme_qr_nse": int(sme_qr) if sme_qr.isdigit() else 0,
            "pending": int(pending_qr) if pending_qr.isdigit() else 0,
            "reviewed": int(reviewed_qr) if reviewed_qr.isdigit() else 0,
            "unique_symbols": int(unique_syms) if unique_syms.isdigit() else 0,
            "sme_stocks_in_db": int(sme_stocks_count) if sme_stocks_count.isdigit() else 0,
            "announcements_log": int(ann_log) if ann_log.isdigit() else 0,
        }
    except Exception as e:
        print(f"  [DB CHECK ERROR] {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("=" * 80)
    print("NSE SME HISTORICAL DATA FEASIBILITY TEST")
    print(f"Period: {START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')}")
    print("=" * 80)

    # Step 1: Check existing DB data
    print("\n[1] CHECKING EXISTING DB DATA...")
    db_info = check_db_existing(START_DATE, END_DATE)
    if db_info:
        print(f"  NSE total in quarterly_results (Apr 1 - May 30): {db_info['total_qr_nse']}")
        print(f"  NSE SME in quarterly_results:                     {db_info['sme_qr_nse']}")
        print(f"  Pending (no valuation):                           {db_info['pending']}")
        print(f"  Reviewed (has valuation):                         {db_info['reviewed']}")
        print(f"  Unique symbols:                                   {db_info['unique_symbols']}")
        print(f"  SME stocks in stocks table (SM/ST series):        {db_info['sme_stocks_in_db']}")
        print(f"  Announcements log entries (NSE, this period):     {db_info['announcements_log']}")
    else:
        print("  Could not connect to DB. Continuing with NSE API test only.")

    # Step 2: Fetch from NSE API day by day
    print("\n[2] FETCHING NSE SME ANNOUNCEMENTS FROM NSE API...")
    print(f"  Strategy: Day-by-day fetch (NSE API requires date range)")
    print(f"  Delay: 2s between requests to avoid rate limiting")

    all_announcements: list[dict] = []
    financial_results: list[dict] = []
    daily_counts: dict[str, dict] = {}
    errors: list[str] = []

    total_days = (END_DATE - START_DATE).days + 1
    weekdays = 0

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, http2=False) as client:
        # Initial session
        print("  Establishing NSE session...", end=" ", flush=True)
        ok = await create_nse_session(client)
        print("OK" if ok else "FAILED")
        await asyncio.sleep(1)

        session_refresh_counter = 0
        current_date = START_DATE

        while current_date <= END_DATE:
            # Skip weekends (NSE closed)
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            weekdays += 1
            date_str = current_date.strftime("%d-%m-%Y")
            date_key = current_date.strftime("%Y-%m-%d")

            # Refresh session every 15 requests
            session_refresh_counter += 1
            if session_refresh_counter % 15 == 0:
                await create_nse_session(client)
                await asyncio.sleep(2)

            rows = await fetch_nse_sme_for_date(client, current_date)

            # If empty/403, retry with fresh session
            if not rows and current_date.weekday() < 5:
                await create_nse_session(client)
                await asyncio.sleep(2)
                rows = await fetch_nse_sme_for_date(client, current_date)

            fin_results = [r for r in rows if _is_financial_result(r)]

            daily_counts[date_key] = {
                "total": len(rows),
                "financial_results": len(fin_results),
            }

            all_announcements.extend(rows)
            financial_results.extend(fin_results)

            status = f"  {date_key} ({current_date.strftime('%a')}): {len(rows):>4} total, {len(fin_results):>3} financial results"
            if len(rows) == 0:
                status += " [EMPTY/HOLIDAY?]"
            print(status)

            await asyncio.sleep(2)  # Rate limit
            current_date += timedelta(days=1)

    # Step 3: Analysis
    print("\n" + "=" * 80)
    print("[3] ANALYSIS RESULTS")
    print("=" * 80)

    # Unique symbols
    all_symbols = set(r.get("symbol", "") for r in all_announcements if r.get("symbol"))
    fr_symbols = set(r.get("symbol", "") for r in financial_results if r.get("symbol"))

    print(f"\n  OVERALL COUNTS:")
    print(f"  {'Total trading days checked:':<40} {weekdays}")
    print(f"  {'Total announcements (all types):':<40} {len(all_announcements)}")
    print(f"  {'Financial results only:':<40} {len(financial_results)}")
    print(f"  {'Unique symbols (all announcements):':<40} {len(all_symbols)}")
    print(f"  {'Unique symbols (financial results):':<40} {len(fr_symbols)}")

    # Monthly breakdown
    print(f"\n  MONTHLY BREAKDOWN:")
    apr_ann = [r for r in all_announcements if "Apr" in (r.get("an_dt") or r.get("dt") or "") or
               any(d.startswith("2026-04") for d in [daily_counts.get(r.get("_date", ""), {}).get("date", "")])]
    may_ann = [r for r in all_announcements if "May" in (r.get("an_dt") or r.get("dt") or "")]

    apr_total = sum(v["total"] for k, v in daily_counts.items() if k.startswith("2026-04"))
    apr_fr = sum(v["financial_results"] for k, v in daily_counts.items() if k.startswith("2026-04"))
    may_total = sum(v["total"] for k, v in daily_counts.items() if k.startswith("2026-05"))
    may_fr = sum(v["financial_results"] for k, v in daily_counts.items() if k.startswith("2026-05"))

    print(f"  {'Month':<10} {'Total Ann':>12} {'Fin Results':>12}")
    print(f"  {'-' * 36}")
    print(f"  {'April':<10} {apr_total:>12} {apr_fr:>12}")
    print(f"  {'May':<10} {may_total:>12} {may_fr:>12}")
    print(f"  {'-' * 36}")
    print(f"  {'TOTAL':<10} {apr_total + may_total:>12} {apr_fr + may_fr:>12}")

    # Category breakdown
    print(f"\n  ANNOUNCEMENT CATEGORIES (desc field):")
    desc_counter = Counter(r.get("desc", "Unknown") for r in all_announcements)
    print(f"  {'Category':<55} {'Count':>6}")
    print(f"  {'-' * 63}")
    for desc, count in desc_counter.most_common(20):
        print(f"  {desc[:55]:<55} {count:>6}")

    # Financial results - symbols breakdown
    if financial_results:
        print(f"\n  TOP 10 SYMBOLS WITH MOST FINANCIAL RESULTS:")
        sym_counter = Counter(r.get("symbol", "?") for r in financial_results)
        print(f"  {'Symbol':<20} {'Company':<30} {'Count':>6}")
        print(f"  {'-' * 58}")
        for sym, count in sym_counter.most_common(10):
            company = next((r.get("sm_name", "") for r in financial_results if r.get("symbol") == sym), "")
            print(f"  {sym:<20} {company[:30]:<30} {count:>6}")

    # Gap analysis: What's in NSE API but NOT in our DB?
    if db_info:
        print(f"\n  GAP ANALYSIS (NSE API vs DB):")
        print(f"  {'Financial results from NSE API:':<45} {len(financial_results)}")
        print(f"  {'Already in DB (quarterly_results, NSE):':<45} {db_info['total_qr_nse']}")
        print(f"  {'Potential new entries to migrate:':<45} {max(0, len(financial_results) - db_info['total_qr_nse'])}")
        print(f"  {'Unique FR symbols from API:':<45} {len(fr_symbols)}")

    # Save detailed report
    report = {
        "period": f"{START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')}",
        "summary": {
            "total_days_checked": weekdays,
            "total_announcements": len(all_announcements),
            "financial_results_count": len(financial_results),
            "unique_symbols_all": len(all_symbols),
            "unique_symbols_fr": len(fr_symbols),
        },
        "monthly": {
            "april": {"total": apr_total, "financial_results": apr_fr},
            "may": {"total": may_total, "financial_results": may_fr},
        },
        "daily_counts": daily_counts,
        "categories": dict(desc_counter.most_common()),
        "fr_symbols": sorted(fr_symbols),
        "db_existing": db_info,
    }

    report_path = OUTPUT_DIR / f"nse_sme_historical_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    # Save raw financial results data
    fr_path = OUTPUT_DIR / f"nse_sme_financial_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    fr_path.write_text(json.dumps(financial_results, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'=' * 80}")
    print("FILES SAVED:")
    print(f"  Report: {report_path.name}")
    print(f"  Financial Results: {fr_path.name}")
    print(f"{'=' * 80}")

    # Recommendation
    print(f"\n{'=' * 80}")
    print("RECOMMENDATION")
    print(f"{'=' * 80}")
    if len(financial_results) > 0:
        print(f"  FEASIBLE: Found {len(financial_results)} financial result announcements")
        print(f"  from {len(fr_symbols)} unique NSE SME symbols.")
        print(f"")
        print(f"  Next steps:")
        print(f"    1. Build migration script to insert these into quarterly_results")
        print(f"    2. Trigger AI extraction for each (or bulk process)")
        print(f"    3. They will appear on PE Pending page with segment=NSE_SME")
        print(f"    4. Estimated processing time: ~{len(financial_results) * 15}s ({len(financial_results) * 15 / 60:.0f} min) for extraction")
    else:
        print(f"  NO DATA: NSE API returned 0 financial results for SME in this period.")
        print(f"  This could mean:")
        print(f"    - NSE API doesn't serve historical data this far back")
        print(f"    - Rate limiting blocked all requests")
        print(f"    - Try a shorter date range or different approach")

    print(f"\n{'=' * 80}")
    print("DONE")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    asyncio.run(main())
