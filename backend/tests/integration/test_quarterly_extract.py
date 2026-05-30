"""
Standalone test for quarterly results extraction + PE calculation.
Usage: python test_quarterly_extract.py <pdf_path_or_url> [SYMBOL]

Examples:
  python test_quarterly_extract.py "C:/path/to/result.pdf" TCS
  python test_quarterly_extract.py "https://www.bseindia.com/xml-data/corpfiling/AttachLive/xxx.pdf" ERIS
"""
import asyncio
import sys
import json
import time
import os
import aiohttp
import pandas as pd
from io import StringIO
from datetime import datetime
from typing import Any, Dict, List, Optional
from async_ocr_from_image import (
    download_pdf_async, pdf_to_png_async,
    process_ocr_all_financial_pages_async, encode_images_async,
    analyze_quarterly_results_async
)
from dotenv import load_dotenv
load_dotenv()

DEFAULT_DPI = 120
IMAGE_CHUNK_SIZE = 2


def chunk_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    if chunk_size <= 0:
        return [items]
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def merge_periods(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = []
    seen = set()

    for period in existing + incoming:
        if not isinstance(period, dict):
            continue
        key = (
            str(period.get("column_header")),
            str(period.get("period_type")),
            str(period.get("quarter")),
            str(period.get("financial_year")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(period)

    return merged


def merge_quarterly_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    final_result: Dict[str, Any] = {
        "company_name": None,
        "units": None,
        "standalone_periods": [],
        "consolidated_periods": [],
    }
    errors = []

    for res in results:
        if not isinstance(res, dict):
            continue

        if not final_result["company_name"] and res.get("company_name"):
            final_result["company_name"] = res.get("company_name")
        if not final_result["units"] and res.get("units"):
            final_result["units"] = res.get("units")

        final_result["standalone_periods"] = merge_periods(
            final_result["standalone_periods"], res.get("standalone_periods", [])
        )
        final_result["consolidated_periods"] = merge_periods(
            final_result["consolidated_periods"], res.get("consolidated_periods", [])
        )

        if res.get("error"):
            errors.append(res["error"])

    if errors and not final_result["standalone_periods"] and not final_result["consolidated_periods"]:
        final_result["error"] = "; ".join(errors)
    elif errors:
        final_result["warnings"] = errors

    final_result["merge_metadata"] = {
        "chunks_processed": len(results),
        "standalone_periods": len(final_result["standalone_periods"]),
        "consolidated_periods": len(final_result["consolidated_periods"]),
    }

    return final_result


async def analyze_quarterly_in_parallel(image_paths: List[str], fallback_text: str) -> Dict[str, Any]:
    if not image_paths:
        return await analyze_quarterly_results_async(fallback_text, [])

    image_chunks = chunk_list(image_paths, IMAGE_CHUNK_SIZE)
    print(f"🧩 Splitting {len(image_paths)} financial pages into {len(image_chunks)} AI chunks (size={IMAGE_CHUNK_SIZE})")

    async def process_chunk(chunk_idx: int, chunk_paths: List[str]) -> Dict[str, Any]:
        print(f"🚀 Chunk {chunk_idx + 1}: encoding {len(chunk_paths)} images")
        chunk_encoded_images = await encode_images_async(chunk_paths)
        print(f"🤖 Chunk {chunk_idx + 1}: running quarterly AI analysis")
        return await analyze_quarterly_results_async(fallback_text, chunk_encoded_images)

    chunk_tasks = [process_chunk(i, chunk) for i, chunk in enumerate(image_chunks)]
    chunk_results = await asyncio.gather(*chunk_tasks)
    print(f"✅ Completed {len(chunk_results)} chunked AI calls")
    return merge_quarterly_results(chunk_results)


def parse_period_date(column_header: str) -> datetime:
    """Parse column_header like '30.06.2025' or '31.03.2025' to datetime."""
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(column_header.strip(), fmt)
        except ValueError:
            continue
    return datetime.min


def calculate_full_year_eps(periods: List[Dict[str, Any]], eps_key: str = "eps_basic") -> Dict[str, Any]:
    """
    Calculate full_year_estimated_EPS from extracted quarterly periods.

    Identifies the current (latest date) quarter and applies:
      Q1 -> Q1 * 4
      Q2 -> (Q1 + Q2) * 2
      Q3 -> (Q1 + Q2 + Q3) * 4/3
      Q4 / FY -> FY EPS directly (annual period)
    """
    if not periods:
        return {"error": "no periods"}

    quarterly = [p for p in periods if p.get("period_type") == "quarter"]
    annual = [p for p in periods if p.get("period_type") == "annual"]

    if not quarterly and not annual:
        return {"error": "no quarter or annual periods found"}

    quarterly.sort(key=lambda p: parse_period_date(p.get("column_header", "")), reverse=True)

    latest = quarterly[0] if quarterly else None
    current_q = latest.get("quarter", "").upper() if latest else None
    current_fy = latest.get("financial_year", "") if latest else None

    same_fy_quarters = {}
    for p in quarterly:
        if p.get("financial_year") == current_fy:
            q = p.get("quarter", "").upper()
            eps = p.get(eps_key)
            if eps is not None and q:
                same_fy_quarters[q] = eps

    fy_eps = None
    for a in annual:
        if a.get("financial_year") == current_fy:
            fy_eps = a.get(eps_key)
            break

    result = {
        "current_quarter": current_q,
        "financial_year": current_fy,
        "latest_date": latest.get("column_header") if latest else None,
        "eps_key_used": eps_key,
        "quarters_available": same_fy_quarters,
        "fy_annual_eps": fy_eps,
    }

    if current_q == "Q4" or (not current_q and fy_eps is not None):
        result["formula"] = "FY EPS (annual)"
        result["full_year_estimated_eps"] = fy_eps
    elif current_q == "Q1":
        q1 = same_fy_quarters.get("Q1")
        if q1 is not None:
            result["formula"] = "Q1 * 4"
            result["full_year_estimated_eps"] = round(q1 * 4, 4)
        else:
            result["error"] = "Q1 EPS missing"
    elif current_q == "Q2":
        q1 = same_fy_quarters.get("Q1")
        q2 = same_fy_quarters.get("Q2")
        if q1 is not None and q2 is not None:
            result["formula"] = "(Q1 + Q2) * 2"
            result["full_year_estimated_eps"] = round((q1 + q2) * 2, 4)
        elif q2 is not None:
            result["formula"] = "Q2 * 4 (Q1 missing, fallback)"
            result["full_year_estimated_eps"] = round(q2 * 4, 4)
        else:
            result["error"] = "Q2 EPS missing"
    elif current_q == "Q3":
        q1 = same_fy_quarters.get("Q1")
        q2 = same_fy_quarters.get("Q2")
        q3 = same_fy_quarters.get("Q3")
        available = [v for v in [q1, q2, q3] if v is not None]
        if len(available) == 3:
            result["formula"] = "(Q1 + Q2 + Q3) * 4/3"
            result["full_year_estimated_eps"] = round(sum(available) * 4 / 3, 4)
        elif q3 is not None:
            n = len(available)
            result["formula"] = f"sum({n}Q) * 4/{n} (partial fallback)"
            result["full_year_estimated_eps"] = round(sum(available) * 4 / n, 4)
        else:
            result["error"] = "Q3 EPS missing"
    else:
        result["error"] = f"unrecognized quarter: {current_q}"

    return result


def print_eps_analysis(result: Dict[str, Any]):
    """Print full_year_estimated_EPS for both standalone and consolidated."""
    print(f"\n{'='*60}")
    print(f"  EPS ANALYSIS — {result.get('company_name', 'Unknown')}")
    print(f"  Units: {result.get('units', '-')}")
    print(f"{'='*60}")

    for label, key in [("STANDALONE", "standalone_periods"), ("CONSOLIDATED", "consolidated_periods")]:
        periods = result.get(key, [])
        if not periods:
            print(f"\n  [{label}] No data")
            continue

        for eps_key in ("eps_basic", "eps_diluted"):
            calc = calculate_full_year_eps(periods, eps_key)
            fy_eps = calc.get("full_year_estimated_eps")
            print(f"\n  [{label} — {eps_key}]")
            print(f"    Current Quarter : {calc.get('current_quarter')} (FY {calc.get('financial_year')})")
            print(f"    Latest Date     : {calc.get('latest_date')}")
            print(f"    Quarters Found  : {calc.get('quarters_available')}")
            print(f"    FY Annual EPS   : {calc.get('fy_annual_eps')}")
            print(f"    Formula         : {calc.get('formula', calc.get('error', '-'))}")
            print(f"    Full Year Est.  : {fy_eps}")
            if fy_eps:
                print(f"    PE (example)    : LTP / {fy_eps}")

    print(f"\n{'='*60}")


NSE_CM_NEO_GID = "1765483913"
NSE_CM_NEO_URL = f"https://docs.google.com/spreadsheets/d/{os.getenv('sheet_id', '1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM')}/export?format=csv&gid={NSE_CM_NEO_GID}"

_token_cache: Dict[str, int] = {}


async def fetch_nse_token_map() -> Dict[str, int]:
    """Fetch nse_cm_neo sheet and build {SYMBOL: exchange_token} map. Cached after first call."""
    global _token_cache
    if _token_cache:
        return _token_cache

    print(f"📥 Fetching NSE scrip master from Google Sheet...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(NSE_CM_NEO_URL) as resp:
                if resp.status != 200:
                    print(f"❌ Failed to fetch sheet: HTTP {resp.status}")
                    return {}
                csv_text = await resp.text()

        df = pd.read_csv(StringIO(csv_text))
        df.columns = [c.strip() for c in df.columns]

        for _, row in df.iterrows():
            sym_name = str(row.get("pSymbolName", "")).strip()
            token = row.get("pSymbol")
            if not sym_name or pd.isna(token):
                continue
            clean_sym = sym_name.replace("-EQ", "").replace("-BE", "").replace("-SM", "").strip().upper()
            try:
                _token_cache[clean_sym] = int(float(token))
            except (ValueError, TypeError):
                continue

        print(f"✅ Loaded {len(_token_cache)} NSE symbol→token mappings")
    except Exception as e:
        print(f"❌ Error fetching token map: {e}")

    return _token_cache


async def fetch_cmp(symbol: str) -> Optional[float]:
    """Fetch current market price for a symbol using Kotak quote API."""
    token_map = await fetch_nse_token_map()
    token = token_map.get(symbol.upper())
    if not token:
        print(f"⚠️  No exchange token found for {symbol}")
        return None

    try:
        from get_quote import get_single_quote, flatten_quote_result_list
        quote_symbol = f"nse_cm|{token}"
        print(f"📊 Fetching CMP for {symbol} (token={token})...")
        raw = await get_single_quote(quote_symbol)
        if not raw:
            print(f"❌ Quote API returned no data for {symbol}")
            return None

        if isinstance(raw, dict):
            raw_list = [[raw]]
        elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
            raw_list = [raw]
        else:
            raw_list = raw
        flattened = await flatten_quote_result_list(raw_list)
        for q in flattened:
            if q.get("error"):
                continue
            close = q.get("ohlc", {}).get("close")
            if close:
                cmp_raw = float(close)
                cmp = cmp_raw / 100 if cmp_raw > 100000 else cmp_raw
                print(f"✅ CMP for {symbol}: ₹{cmp:.2f} (raw close={cmp_raw})")
                return cmp
        print(f"⚠️  No close price in quote response for {symbol}")
        return None
    except Exception as e:
        print(f"❌ Error fetching CMP for {symbol}: {e}")
        return None


def calculate_pe(cmp: float, fy_eps: float) -> Optional[float]:
    if not cmp or not fy_eps or fy_eps <= 0:
        return None
    return round(cmp / fy_eps, 2)


def print_pe_summary(symbol: str, result: Dict[str, Any], cmp: Optional[float]):
    """Print PE calculation summary."""
    print(f"\n{'='*60}")
    print(f"  PE CALCULATION — {symbol} ({result.get('company_name', 'Unknown')})")
    print(f"{'='*60}")

    cons_periods = result.get("consolidated_periods", [])
    stan_periods = result.get("standalone_periods", [])

    use_label = "CONSOLIDATED" if cons_periods else "STANDALONE"
    use_periods = cons_periods if cons_periods else stan_periods

    if not use_periods:
        print("  ❌ No quarterly data to calculate PE")
        return

    for eps_key in ("eps_basic", "eps_diluted"):
        calc = calculate_full_year_eps(use_periods, eps_key)
        fy_eps = calc.get("full_year_estimated_eps")
        pe = calculate_pe(cmp, fy_eps) if cmp and fy_eps else None

        print(f"\n  [{use_label} — {eps_key}]")
        print(f"    Quarter       : {calc.get('current_quarter')} (FY {calc.get('financial_year')})")
        print(f"    Formula       : {calc.get('formula', calc.get('error', '-'))}")
        print(f"    FY EPS (Est.) : {fy_eps}")
        if cmp:
            print(f"    CMP           : ₹{cmp:.2f}")
        else:
            print(f"    CMP           : — (no Kotak session or token)")
        if pe:
            color = "🟢" if pe < 15 else ("🟡" if pe < 30 else "🔴")
            print(f"    PE            : {pe:.2f} {color}")
        else:
            print(f"    PE            : —")

    print(f"\n{'='*60}")


async def test_extract(source: str, symbol: str = None):
    start = time.time()

    if source.startswith("http"):
        print(f"Downloading PDF from URL...")
        pdf_path = await download_pdf_async(source, "downloads_test")
    else:
        pdf_path = source

    print(f"PDF: {pdf_path}")

    t1 = time.time()
    image_paths, images_folder = await pdf_to_png_async(pdf_path, "images_test", dpi=DEFAULT_DPI)
    print(f"{len(image_paths)} pages converted ({time.time()-t1:.1f}s)")

    t2 = time.time()
    ocr_results = await process_ocr_all_financial_pages_async(image_paths)
    print(f"{len(ocr_results.get('financial_pages', []))} financial pages found ({time.time()-t2:.1f}s)")

    text = ocr_results.get('financial_text') or ocr_results.get('all_pages_text', '')
    print(f"Text length: {len(text)} chars")

    t4 = time.time()
    result = await analyze_quarterly_in_parallel(ocr_results.get('detected_image_paths', []), text)
    print(f"AI extraction done ({time.time()-t4:.1f}s)")

    print(f"\nTotal: {time.time()-start:.1f}s")
    print(f"\n{'='*60}")
    print(json.dumps(result, indent=2))

    print_eps_analysis(result)

    # PE Calculation: fetch CMP and compute PE
    cmp = None
    if symbol:
        cmp = await fetch_cmp(symbol)
    print_pe_summary(symbol or "UNKNOWN", result, cmp)

    try:
        import shutil
        if images_folder:
            shutil.rmtree(images_folder, True)
    except Exception:
        pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_quarterly_extract.py <pdf_path_or_url> [SYMBOL]")
        sys.exit(1)
    src = sys.argv[1]
    sym = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(test_extract(src, sym))
