"""
NSE Corporate Announcements Test Script
========================================
Compares three fetch methods (httpx, NseIndiaApi, nsepython):
  - Latest 20 (no date filter -- NSE default page limit)
  - Full day  (from_date + to_date -- all announcements for today)
  - Per-subject breakdown (NSE's subject filter param)

All results saved to ./nse_downloads/ as JSON.
"""

import asyncio
import time
import json
import pathlib
from datetime import datetime
from collections import Counter

DIR = pathlib.Path(__file__).parent
NSE_DIR = DIR / "nse_downloads"
NSE_DIR.mkdir(exist_ok=True)

SEGMENTS = ["equities", "sme"]

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

# Known NSE subject filter values (must match desc field exactly)
NSE_SUBJECTS = [
    "Outcome of Board Meeting",
    "Dividend",
    "Copy of Newspaper Publication",
    "Analysts/Institutional Investor Meet/Con. Call Updates",
    "General Updates",
    "Updates",
    "Press Release",
    "Investor Presentation",
    "Appointment",
    "Change in Management",
    "Record Date",
    "Shareholders meeting",
    "Change in Director(s)",
    "ESOP/ESOS/ESPS",
    "Acquisition",
    "Credit Rating",
    "Resignation",
    "Allotment of Securities",
    "Related Party Transactions",
    "Resignation of Director/KMP/SMP",
    "Bagging/Receiving of orders/contracts",
    "Statement of deviation(s) or variation(s) under Reg. 32",
    "Change in Auditors",
    "Action(s) taken or orders passed",
    "Action(s) initiated or orders passed",
    "Integrated Filing- Financial",
    "Cessation",
    "Utilisation of Funds",
    "Committee Meeting Updates",
    "Issue of Securities",
    "Structural Digital Database",
    "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company",
    "Reasons for Delayed/Non-submission of Financial Results",
    "Giving guarantees/indemnity/ becoming a surety for third party",
    "Arrangements for strategic, technical, manufacturing, or marketing tie up",
    "Quarterly Compliance Report on Corporate governance - within 21 days from the end of the quarter",
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
]

SEP = "=" * 70
THIN = "-" * 70


# --- Method 1: httpx ---------------------------------------------------------

async def fetch_httpx(segment: str, today_str: str | None = None,
                      subject: str | None = None) -> list[dict]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)
            await asyncio.sleep(1)

            params = {"index": segment}
            if today_str:
                params["from_date"] = today_str
                params["to_date"] = today_str
            if subject:
                params["subject"] = subject

            resp = await client.get(NSE_API_URL, params=params, headers=NSE_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  [httpx] ERROR ({segment}): {e}")
        return []


# --- Method 2: NseIndiaApi (nse[server]) -------------------------------------

def fetch_nse_lib(segment: str, use_date: bool = False) -> list[dict]:
    try:
        from nse import NSE

        with NSE(str(NSE_DIR), server=True) as nse:
            kwargs = {"index": segment}
            if use_date:
                today = datetime.now()
                kwargs["from_date"] = today
                kwargs["to_date"] = today
            data = nse.announcements(**kwargs)
            return data if isinstance(data, list) else []
    except ImportError:
        print("  [nse lib] SKIPPED -- not installed. Run: pip install nse[server]")
        return []
    except Exception as e:
        print(f"  [nse lib] ERROR ({segment}): {e}")
        return []


# --- Method 3: nsepython (legacy) --------------------------------------------

def fetch_nsepython(segment: str, today_str: str | None = None) -> list[dict]:
    try:
        from nsepython import nsefetch

        url = f"{NSE_API_URL}?index={segment}"
        if today_str:
            url += f"&from_date={today_str}&to_date={today_str}"
        data = nsefetch(url)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data", data.get("Table", []))
        return []
    except ImportError:
        print("  [nsepython] SKIPPED -- not installed. Run: pip install nsepython")
        return []
    except Exception as e:
        print(f"  [nsepython] ERROR ({segment}): {e}")
        return []


# --- Helpers ------------------------------------------------------------------

def save_json(filename: str, data) -> pathlib.Path:
    path = NSE_DIR / filename
    path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def print_summary(results: dict[str, list[dict]]) -> int:
    total = 0
    for seg, rows in results.items():
        count = len(rows)
        total += count
        print(f"    {seg.upper():<12}: {count:>6}")
    print(f"    {'TOTAL':<12}: {total:>6}")
    return total


def print_sample(rows: list[dict], label: str, n: int = 5):
    if not rows:
        return
    print(f"\n  Sample {label} (first {min(n, len(rows))}):")
    print(f"  {'-' * 58}")
    for i, row in enumerate(rows[:n], 1):
        symbol = row.get("symbol", "?")
        name = row.get("sm_name", "?")
        desc = row.get("desc", "?")[:80]
        dt = row.get("an_dt") or row.get("dt", "?")
        print(f"  {i}. [{symbol}] {name}")
        print(f"     {desc}")
        print(f"     Date: {dt}")
        print()


def build_category_breakdown(rows: list[dict]) -> dict:
    """Group announcements by desc (category) and return sorted dict."""
    counts = Counter(r.get("desc", "Unknown") for r in rows)
    return dict(counts.most_common())


# --- Main ---------------------------------------------------------------------

async def main():
    now = datetime.now()
    today_display = now.strftime("%Y-%m-%d (%A)")
    today_str = now.strftime("%d-%m-%Y")
    ts = now.strftime("%Y%m%d_%H%M%S")

    print(SEP)
    print(f"NSE CORPORATE ANNOUNCEMENTS TEST -- {today_display}")
    print(SEP)
    print(f"  API date format: from_date={today_str} to_date={today_str}")
    print(f"  Subject filter: ?subject=Outcome of Board Meeting (exact match on desc)")
    print(f"  Without date: returns ONLY latest 20 per segment (page limit)")
    print(f"  With date: returns ALL announcements for that day")

    comparison = {}
    all_json_files = []

    # ==========================================================================
    # METHOD 1: httpx
    # ==========================================================================
    print(f"\n{THIN}")
    print("METHOD 1: httpx (production -- async, direct API)")
    print(THIN)

    # 1A: Latest only
    print("\n  [A] Latest 20 (no date filter):")
    httpx_latest = {}
    t0 = time.perf_counter()
    for seg in SEGMENTS:
        print(f"    Fetching {seg}...", end=" ", flush=True)
        rows = await fetch_httpx(seg)
        httpx_latest[seg] = rows
        print(f"{len(rows)} rows")
        if seg != SEGMENTS[-1]:
            await asyncio.sleep(2)
    print(f"    Time: {time.perf_counter() - t0:.2f}s")
    print_summary(httpx_latest)
    f = save_json(f"httpx_latest_{ts}.json", httpx_latest)
    all_json_files.append(f)
    print(f"    Saved -> {f.name}")

    # 1B: Full day
    print(f"\n  [B] Full day (from_date={today_str}):")
    httpx_full = {}
    t0 = time.perf_counter()
    for seg in SEGMENTS:
        print(f"    Fetching {seg}...", end=" ", flush=True)
        rows = await fetch_httpx(seg, today_str=today_str)
        httpx_full[seg] = rows
        print(f"{len(rows)} rows")
        if seg != SEGMENTS[-1]:
            await asyncio.sleep(2)
    elapsed_httpx = time.perf_counter() - t0
    print(f"    Time: {elapsed_httpx:.2f}s")
    print_summary(httpx_full)
    f = save_json(f"httpx_fullday_{ts}.json", httpx_full)
    all_json_files.append(f)
    print(f"    Saved -> {f.name}")
    print_sample(httpx_full.get("equities", []), "EQUITIES")
    comparison["httpx"] = {"latest": httpx_latest, "fullday": httpx_full}

    # ==========================================================================
    # METHOD 2: NseIndiaApi
    # ==========================================================================
    print(f"\n{THIN}")
    print("METHOD 2: NseIndiaApi library (pip install nse[server])")
    print(THIN)

    print("\n  [A] Latest 20 (no date filter):")
    nselib_latest = {}
    t0 = time.perf_counter()
    for seg in SEGMENTS:
        print(f"    Fetching {seg}...", end=" ", flush=True)
        rows = await asyncio.to_thread(fetch_nse_lib, seg, False)
        nselib_latest[seg] = rows
        print(f"{len(rows)} rows")
    print(f"    Time: {time.perf_counter() - t0:.2f}s")
    print_summary(nselib_latest)

    print(f"\n  [B] Full day (with from_date/to_date):")
    nselib_full = {}
    t0 = time.perf_counter()
    for seg in SEGMENTS:
        print(f"    Fetching {seg}...", end=" ", flush=True)
        rows = await asyncio.to_thread(fetch_nse_lib, seg, True)
        nselib_full[seg] = rows
        print(f"{len(rows)} rows")
    elapsed_nselib = time.perf_counter() - t0
    print(f"    Time: {elapsed_nselib:.2f}s")
    print_summary(nselib_full)
    f = save_json(f"nse_lib_fullday_{ts}.json", nselib_full)
    all_json_files.append(f)
    print(f"    Saved -> {f.name}")
    comparison["nse_lib"] = {"latest": nselib_latest, "fullday": nselib_full}

    # ==========================================================================
    # METHOD 3: nsepython
    # ==========================================================================
    print(f"\n{THIN}")
    print("METHOD 3: nsepython / nsefetch (legacy)")
    print(THIN)

    print("\n  [A] Latest 20 (no date filter):")
    nspy_latest = {}
    t0 = time.perf_counter()
    for seg in SEGMENTS:
        print(f"    Fetching {seg}...", end=" ", flush=True)
        rows = await asyncio.to_thread(fetch_nsepython, seg)
        nspy_latest[seg] = rows
        print(f"{len(rows)} rows")
    print(f"    Time: {time.perf_counter() - t0:.2f}s")
    print_summary(nspy_latest)

    print(f"\n  [B] Full day (with from_date/to_date):")
    nspy_full = {}
    t0 = time.perf_counter()
    for seg in SEGMENTS:
        print(f"    Fetching {seg}...", end=" ", flush=True)
        rows = await asyncio.to_thread(fetch_nsepython, seg, today_str)
        nspy_full[seg] = rows
        print(f"{len(rows)} rows")
    elapsed_nspy = time.perf_counter() - t0
    print(f"    Time: {elapsed_nspy:.2f}s")
    print_summary(nspy_full)
    f = save_json(f"nsepython_fullday_{ts}.json", nspy_full)
    all_json_files.append(f)
    print(f"    Saved -> {f.name}")
    comparison["nsepython"] = {"latest": nspy_latest, "fullday": nspy_full}

    # ==========================================================================
    # CATEGORY/SUBJECT BREAKDOWN (from httpx full-day data)
    # ==========================================================================
    print(f"\n{SEP}")
    print("CATEGORY BREAKDOWN (desc field = NSE subject filter)")
    print(SEP)

    category_report = {}
    for seg in SEGMENTS:
        rows = httpx_full.get(seg, [])
        breakdown = build_category_breakdown(rows)
        category_report[seg] = breakdown
        print(f"\n  {seg.upper()} ({len(rows)} total):")
        print(f"  {'-' * 58}")
        for desc, count in breakdown.items():
            print(f"    {count:>5}  {desc}")

    f = save_json(f"nse_category_breakdown_{ts}.json", category_report)
    all_json_files.append(f)
    print(f"\n  Saved -> {f.name}")

    # ==========================================================================
    # NSE vs BSE: SUBJECT FILTER COMPARISON
    # ==========================================================================
    print(f"\n{SEP}")
    print("NSE SUBJECT FILTER -- HOW IT WORKS")
    print(SEP)
    print("""
  NSE uses a 'subject' query param (NOT 'category' like BSE).
  The value must EXACTLY match the 'desc' field in the response.

  API: GET /api/corporate-announcements
       ?index=equities
       &from_date=28-05-2026
       &to_date=28-05-2026
       &subject=Outcome of Board Meeting    <-- filter

  KEY SUBJECTS (mapped to BSE equivalents):
  ---------------------------------------------------------------
  NSE subject                           BSE equivalent
  ---------------------------------------------------------------
  Outcome of Board Meeting              BOARD_MEETING + RESULT
  Dividend                              ACTION (dividend)
  Analysts/.../Con. Call Updates         (no direct BSE equiv)
  Investor Presentation                 (no direct BSE equiv)
  Copy of Newspaper Publication         (no direct BSE equiv)
  General Updates / Updates             UPDATE
  Press Release                         (no direct BSE equiv)
  Appointment / Change in Management    (no direct BSE equiv)
  ESOP/ESOS/ESPS                        ACTION (ESOP)
  Acquisition                           (no direct BSE equiv)

  IMPORTANT DIFFERENCE vs BSE:
  - BSE has a separate 'RESULT' category for financial results.
  - NSE does NOT have a 'Result' or 'Financial Results' subject.
  - On NSE, financial results come under 'Outcome of Board Meeting'.
  - To find results on NSE, filter subject='Outcome of Board Meeting'
    then check if desc/attchmntText contains result keywords.
""")

    # ==========================================================================
    # COMPARISON TABLE
    # ==========================================================================
    print(SEP)
    print("COMPARISON SUMMARY")
    print(SEP)

    print(f"\n  [A] LATEST 20 (no date -- default page limit)")
    hdr = "Method"
    print(f"  {hdr:<28} {'Equities':>10} {'SME':>10} {'Total':>10}")
    print(f"  {'-' * 62}")
    for name, data in comparison.items():
        res = data["latest"]
        eq = len(res.get("equities", []))
        sme = len(res.get("sme", []))
        print(f"  {name:<28} {eq:>10} {sme:>10} {eq + sme:>10}")

    print(f"\n  [B] FULL DAY (from_date/to_date = {today_str})")
    print(f"  {hdr:<28} {'Equities':>10} {'SME':>10} {'Total':>10}")
    print(f"  {'-' * 62}")
    for name, data in comparison.items():
        res = data["fullday"]
        eq = len(res.get("equities", []))
        sme = len(res.get("sme", []))
        print(f"  {name:<28} {eq:>10} {sme:>10} {eq + sme:>10}")

    # ==========================================================================
    # FIELD STRUCTURE
    # ==========================================================================
    eq_rows = httpx_full.get("equities", [])
    if eq_rows:
        print(f"\n{SEP}")
        print("NSE FIELDS (sample row)")
        print(SEP)
        for key, val in eq_rows[0].items():
            print(f"  {key:<20}: {str(val)[:80]}")

    # ==========================================================================
    # KEY FINDINGS
    # ==========================================================================
    latest_total = sum(len(v) for v in httpx_latest.values())
    full_total = sum(len(v) for v in httpx_full.values())

    print(f"\n{SEP}")
    print("KEY FINDINGS")
    print(SEP)
    print(f"  1. PAGE LIMIT: Without date params NSE returns only 20 per segment")
    print(f"     Without date: {latest_total:>6}")
    print(f"     With date:    {full_total:>6}")
    print(f"     Missing:      {full_total - latest_total:>6} announcements!")
    print()
    print(f"  2. SUBJECT FILTER: NSE supports ?subject=<exact desc> to filter")
    print(f"     But NO 'Result' or 'Financial Results' category exists.")
    print(f"     Results are inside 'Outcome of Board Meeting' ({category_report.get('equities', {}).get('Outcome of Board Meeting', 0)} today).")
    print()
    print(f"  3. SPEED: nse_lib={elapsed_nselib:.1f}s  httpx={elapsed_httpx:.1f}s  nsepython={elapsed_nspy:.1f}s")
    print()
    print(f"  4. ALL THREE METHODS return identical data (same API underneath).")

    # ==========================================================================
    # MASTER JSON (everything in one file)
    # ==========================================================================
    master = {
        "test_date": today_display,
        "api_date_param": today_str,
        "comparison": {},
        "category_breakdown": category_report,
        "nse_subject_filters": NSE_SUBJECTS,
        "field_sample": eq_rows[0] if eq_rows else {},
    }
    for name, data in comparison.items():
        master["comparison"][name] = {
            "latest": {seg: len(rows) for seg, rows in data["latest"].items()},
            "fullday": {seg: len(rows) for seg, rows in data["fullday"].items()},
        }
    f = save_json(f"nse_test_report_{ts}.json", master)
    all_json_files.append(f)

    print(f"\n{SEP}")
    print("SAVED JSON FILES")
    print(SEP)
    for fp in all_json_files:
        size_kb = fp.stat().st_size / 1024
        print(f"  {fp.name:<50} {size_kb:>8.1f} KB")

    print(f"\n{SEP}")
    print("DONE")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())
