"""
Test: PyMuPDF (fitz) for financial page detection + OpenAI Vision extraction.
Extracts quarterly results, stores in DB, fetches CMP, computes PE.

Usage: python test_pymupdf_speed.py <pdf_path> SYMBOL [--exchange NSE|BSE] [--no-cmp]
"""

import sys
import os
import time
import json
import base64
import fitz  # PyMuPDF
import asyncio
import aiosqlite
import aiohttp
import pandas as pd
from datetime import datetime, timezone, timedelta
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv('DB_PATH', 'messages.db')
IST = timezone(timedelta(hours=5, minutes=30))

FINANCIAL_KEYWORDS = ['revenue', 'expense', 'tax', 'profit', 'earning',
                      'income', 'eps', 'share capital', 'diluted', 'comprehensive']
MIN_KEYWORD_MATCHES = 3


def extract_text_pymupdf(pdf_path: str) -> list[dict]:
    """Extract text from each page using PyMuPDF. Works for text-based PDFs."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        pages.append({"page_num": i + 1, "text": text, "has_text": bool(text.strip())})
    doc.close()
    return pages


def render_page_to_png(pdf_path: str, page_num: int, dpi: int = 150) -> bytes:
    """Render a single page to PNG bytes using PyMuPDF (no Poppler needed)."""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


def find_financial_pages(pages: list[dict]) -> list[int]:
    """Filter pages that contain financial keywords."""
    financial = []
    for p in pages:
        text_lower = p["text"].lower()
        matches = sum(1 for kw in FINANCIAL_KEYWORDS if kw in text_lower)
        if matches >= MIN_KEYWORD_MATCHES:
            financial.append(p["page_num"])
            print(f"  Page {p['page_num']}: {matches}/{len(FINANCIAL_KEYWORDS)} keywords matched")
    return financial


def find_financial_pages_image_fallback(pdf_path: str, total_pages: int) -> list[int]:
    """
    For image-based PDFs where text extraction fails:
    Send first N pages as candidates (financial tables are usually in first 5-6 pages).
    Let OpenAI handle the filtering — it's already doing the extraction.
    """
    candidates = list(range(1, min(total_pages + 1, 7)))
    print(f"  Image PDF fallback: sending pages {candidates} to AI")
    return candidates


async def call_openai_vision(encoded_images: list[str]) -> dict:
    """Single OpenAI call with all financial page images."""
    client = AsyncOpenAI()

    base_prompt = """You are extracting data from an Indian company's quarterly financial results PDF.

The document may have TWO tables: Standalone and Consolidated (check the title of each table).

**TABLE STRUCTURE:**
Each table typically has 4-6+ data columns:
- 3 columns under "Quarter ended" header (individual quarterly periods)
- 0-2 columns under "Six Month ended" / "Nine Month ended" header (cumulative periods — NOT always present)
- 1 column under "Year Ended" header (full year annual data)
You MUST extract ALL columns as separate entries — quarterly, cumulative, AND annual.

**ROW STRUCTURE (top to bottom in each table):**
Row 1: "Revenue from Operations" — this is the FIRST income row
Row 2: "Other Income" — this is the SECOND income row (separate from Revenue)
Row 3: "Total Income" — sum row
Then expense rows, then profit rows, then tax, then EPS at bottom.

**CRITICAL — DASH HANDLING:**
- A dash (-) means null. Return null, not 0, not 0.0.

**face_value:** Read from the row label text "Face Value Rs. X/- Each".

**Quarter & Financial Year mapping (Indian FY):**
- June ending → Q1, FY = next March's year
- September ending → Q2, FY = next March's year
- December ending → Q3, FY = next March's year
- March ending → Q4, FY = same year
- Year Ended column → period_type = "annual", quarter = "FY"

**period_type mapping for cumulative columns:**
- "Six Month ended" column → period_type = "six_month", quarter = same as matching quarterly date (Q2)
- "Nine Month ended" column → period_type = "nine_month", quarter = same as matching quarterly date (Q3)
- These are FULL entries with ALL rows extracted (revenue, expenses, PAT, EPS, etc.), same schema as quarterly entries.

IMPORTANT: Return ONLY raw JSON. No markdown, no code blocks.
If a page is NOT a financial results table, IGNORE it completely.

{
    "company_name": "string",
    "units": "lakhs or crores",
    "standalone_periods": [
        {
            "column_header": "30.06.2025",
            "period_type": "quarter | six_month | nine_month | annual",
            "quarter": "Q1",
            "financial_year": "2026",
            "revenue_from_operations": number_or_null,
            "other_income": number_or_null,
            "total_income": number_or_null,
            "total_expenses": number_or_null,
            "profit_before_exceptional": number_or_null,
            "exceptional_items": number_or_null,
            "profit_before_tax": number_or_null,
            "tax_expense": number_or_null,
            "profit_after_tax": number_or_null,
            "profit_attributable_to_minority": number_or_null,
            "other_comprehensive_income": number_or_null,
            "total_comprehensive_income": number_or_null,
            "paid_up_equity_share_capital": number_or_null,
            "face_value": number_or_null,
            "eps_basic": number_or_null,
            "eps_diluted": number_or_null
        }
    ],
    "consolidated_periods": []
}

Rules:
- Extract EVERY data column as a separate entry: quarterly columns + cumulative columns (six_month/nine_month) + annual column.
- A Q3 PDF typically has: 3 quarterly + 2 nine_month + 1 annual = 6 entries per table.
- A Q2 PDF typically has: 3 quarterly + 2 six_month + 1 annual = 6 entries per table.
- null for dash (-) or blank cells. Never use 0 or 0.0 for dashes.
- Return numbers exactly as printed in the document."""

    content = [{"type": "text", "text": base_prompt}]
    for img_b64 in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })
    content.append({
        "type": "text",
        "text": "\nSTEP-BY-STEP EXTRACTION:\n"
               "1. Each image = one table (Standalone or Consolidated). Identify which from the title.\n"
               "2. Locate ALL data columns: quarterly + cumulative (Six/Nine Month ended) + annual (Year Ended).\n"
               "3. For EACH column (including cumulative), extract ALL rows as a full entry with the correct period_type.\n"
               "4. Cumulative columns get period_type 'six_month' or 'nine_month', with quarter matching the date.\n"
               "5. Do NOT skip any column. Do NOT skip the Year Ended column.\n"
               "6. VERIFY per column: Total Income ≈ Revenue + Other Income."
    })

    t0 = time.time()
    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": content}],
        temperature=0,
        max_tokens=16000,
        response_format={"type": "json_object"}
    )
    elapsed = time.time() - t0

    result_text = response.choices[0].message.content
    usage = response.usage
    print(f"\n  OpenAI call: {elapsed:.1f}s | tokens: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}")

    return json.loads(result_text)


def _parse_period_date(column_header: str):
    """Parse column_header like '30.06.2025' to datetime for sorting."""
    from datetime import datetime
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(column_header).strip(), fmt)
        except (ValueError, TypeError):
            continue
    from datetime import datetime as dt
    return dt.min


def calculate_fy_eps(periods: list[dict], eps_key: str = "eps_basic") -> dict:
    """
    Prefers cumulative period entries (nine_month/six_month) when available, falls back to sum of quarters.
    Q1 -> Q1*4 | Q2 -> N6*2 or (Q1+Q2)*2 | Q3 -> N9*4/3 or (Q1+Q2+Q3)*4/3 | Q4/FY -> annual EPS
    """
    if not periods:
        return {"quarter": None, "fy": None, "formula": None, "value": None}

    quarterly = [p for p in periods if p.get("period_type") == "quarter"]
    annual = [p for p in periods if p.get("period_type") == "annual"]
    nine_month = [p for p in periods if p.get("period_type") == "nine_month"]
    six_month = [p for p in periods if p.get("period_type") == "six_month"]

    if not quarterly and not annual:
        return {"quarter": None, "fy": None, "formula": None, "value": None}

    quarterly.sort(key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True)

    latest = quarterly[0] if quarterly else None
    current_q = latest.get("quarter", "").upper() if latest else None
    current_fy = latest.get("financial_year", "") if latest else None

    cum_eps = None
    if current_q == "Q3" and nine_month:
        nm = [p for p in nine_month if p.get("financial_year") == current_fy]
        nm.sort(key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True)
        if nm:
            cum_eps = nm[0].get(eps_key)
    elif current_q == "Q2" and six_month:
        sm = [p for p in six_month if p.get("financial_year") == current_fy]
        sm.sort(key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True)
        if sm:
            cum_eps = sm[0].get(eps_key)

    same_fy = {}
    for p in quarterly:
        if p.get("financial_year") == current_fy:
            q = p.get("quarter", "").upper()
            eps = p.get(eps_key)
            if eps is not None and q:
                same_fy[q] = eps

    fy_eps = None
    for a in annual:
        if a.get("financial_year") == current_fy:
            fy_eps = a.get(eps_key)
            break

    result = {"quarter": current_q, "fy": current_fy, "formula": None, "value": None}

    if current_q == "Q4" or (not current_q and fy_eps is not None):
        result["formula"] = "FY"
        result["value"] = fy_eps
    elif current_q == "Q1":
        q1 = same_fy.get("Q1")
        if q1 is not None:
            result["formula"] = "Q1*4"
            result["value"] = round(q1 * 4, 4)
    elif current_q == "Q2":
        if cum_eps is not None:
            result["formula"] = "N6*2"
            result["value"] = round(cum_eps * 2, 4)
        else:
            q1, q2 = same_fy.get("Q1"), same_fy.get("Q2")
            if q1 is not None and q2 is not None:
                result["formula"] = "(Q1+Q2)*2"
                result["value"] = round((q1 + q2) * 2, 4)
            elif q2 is not None:
                result["formula"] = "Q2*4"
                result["value"] = round(q2 * 4, 4)
    elif current_q == "Q3":
        if cum_eps is not None:
            result["formula"] = "N9*4/3"
            result["value"] = round(cum_eps * 4 / 3, 4)
        else:
            vals = [same_fy.get(q) for q in ("Q1", "Q2", "Q3")]
            available = [v for v in vals if v is not None]
            if available:
                n = len(available)
                result["formula"] = f"sum({n}Q)*4/{n}"
                result["value"] = round(sum(available) * 4 / n, 4)
    elif current_q == "FY":
        result["formula"] = "FY"
        result["value"] = fy_eps

    return result


def compute_all_fy_eps(ai_response: dict) -> dict:
    """Compute FY EPS for all 4 combinations."""
    standalone = ai_response.get("standalone_periods", [])
    consolidated = ai_response.get("consolidated_periods", [])
    return {
        "standalone_basic": calculate_fy_eps(standalone, "eps_basic"),
        "standalone_diluted": calculate_fy_eps(standalone, "eps_diluted"),
        "consolidated_basic": calculate_fy_eps(consolidated, "eps_basic"),
        "consolidated_diluted": calculate_fy_eps(consolidated, "eps_diluted"),
    }


def print_fy_eps_summary(fy_eps: dict, symbol: str, ai_response: dict = None):
    """Print a clean FY EPS summary table with cumulative period source values."""
    if ai_response:
        cum_vals = []
        for tag, periods in [("Standalone", ai_response.get("standalone_periods", [])),
                             ("Consolidated", ai_response.get("consolidated_periods", []))]:
            for p in periods:
                pt = p.get("period_type", "")
                if pt in ("six_month", "nine_month"):
                    n_label = "N6" if pt == "six_month" else "N9"
                    q = p.get("quarter", "?")
                    fy = p.get("financial_year", "?")
                    cb = p.get("eps_basic")
                    cd = p.get("eps_diluted")
                    cum_vals.append(f"  {tag} {n_label} ({q}/{fy}): basic={cb}, diluted={cd}")
        if cum_vals:
            print(f"\nCumulative periods extracted from PDF:")
            for line in cum_vals:
                print(line)
        else:
            print(f"\nCumulative periods: Not available in this PDF")

    print(f"\nFY EPS ESTIMATES for {symbol}:")
    print(f"  {'Type':<25} {'Quarter':<8} {'FY':<6} {'Formula':<15} {'FY EPS':>10}")
    print(f"  {'-'*25} {'-'*8} {'-'*6} {'-'*15} {'-'*10}")
    for label, data in fy_eps.items():
        q = data.get("quarter") or "-"
        fy = data.get("fy") or "-"
        formula = data.get("formula") or "-"
        val = data.get("value")
        val_str = f"{val:.4f}" if val is not None else "-"
        print(f"  {label:<25} {q:<8} {fy:<6} {formula:<15} {val_str:>10}")


async def get_or_create_stock(db, symbol, company_name=None, exchange=None):
    """Get existing stock_id or auto-insert. Returns stocks.id."""
    symbol = (symbol or "").strip().upper()
    now_iso = datetime.now(IST).isoformat()
    cursor = await db.execute("SELECT id FROM stocks WHERE symbol = ?", (symbol,))
    row = await cursor.fetchone()
    if row:
        return row[0]
    cursor = await db.execute(
        "INSERT INTO stocks (symbol, company_name, exchange, is_active, added_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
        (symbol, company_name, exchange, now_iso, now_iso)
    )
    return cursor.lastrowid


async def store_quarterly_results(ai_response, symbol, exchange, pdf_path):
    """UPSERT quarterly results into DB. Returns list of stored periods."""
    company_name = ai_response.get('company_name')
    units = ai_response.get('units')
    standalone_periods = ai_response.get('standalone_periods', [])
    consolidated_periods = ai_response.get('consolidated_periods', [])

    if not standalone_periods and not consolidated_periods:
        print("  No periods to store")
        return []

    fy_eps = compute_all_fy_eps(ai_response)
    fy_basic_s = fy_eps["standalone_basic"].get("value")
    fy_diluted_s = fy_eps["standalone_diluted"].get("value")
    fy_basic_c = fy_eps["consolidated_basic"].get("value")
    fy_diluted_c = fy_eps["consolidated_diluted"].get("value")
    fy_formula_s = fy_eps["standalone_basic"].get("formula")
    fy_formula_c = fy_eps["consolidated_basic"].get("formula")

    period_map = {}
    cum_map_s = {}
    cum_map_c = {}
    for p in standalone_periods:
        q, fy = p.get('quarter'), p.get('financial_year')
        pt = p.get('period_type', 'quarter')
        if not q or not fy:
            continue
        data = {k: v for k, v in p.items() if k not in ('column_header', 'period_type', 'quarter', 'financial_year')}
        if pt in ('six_month', 'nine_month'):
            cum_map_s[(q, fy)] = data
        else:
            key = (q, fy)
            if key not in period_map:
                period_map[key] = {"period_ended": p.get('column_header'), "standalone": None, "consolidated": None}
            period_map[key]["standalone"] = data

    for p in consolidated_periods:
        q, fy = p.get('quarter'), p.get('financial_year')
        pt = p.get('period_type', 'quarter')
        if not q or not fy:
            continue
        data = {k: v for k, v in p.items() if k not in ('column_header', 'period_type', 'quarter', 'financial_year')}
        if pt in ('six_month', 'nine_month'):
            cum_map_c[(q, fy)] = data
        else:
            key = (q, fy)
            if key not in period_map:
                period_map[key] = {"period_ended": p.get('column_header'), "standalone": None, "consolidated": None}
            period_map[key]["consolidated"] = data

    for (q, fy), cum_data in cum_map_s.items():
        if (q, fy) in period_map and period_map[(q, fy)]["standalone"]:
            period_map[(q, fy)]["standalone"]["cumulative_eps_basic"] = cum_data.get("eps_basic")
            period_map[(q, fy)]["standalone"]["cumulative_eps_diluted"] = cum_data.get("eps_diluted")
    for (q, fy), cum_data in cum_map_c.items():
        if (q, fy) in period_map and period_map[(q, fy)]["consolidated"]:
            period_map[(q, fy)]["consolidated"]["cumulative_eps_basic"] = cum_data.get("eps_basic")
            period_map[(q, fy)]["consolidated"]["cumulative_eps_diluted"] = cum_data.get("eps_diluted")

    now_iso = datetime.now(IST).isoformat()
    stored = []

    async with aiosqlite.connect(DB_PATH) as db:
        stock_id = await get_or_create_stock(db, symbol, company_name, exchange)
        for (quarter, fy), data in period_map.items():
            s_data = data["standalone"]
            c_data = data["consolidated"]
            eps_basic_s = s_data.get('eps_basic') if s_data else None
            eps_diluted_s = s_data.get('eps_diluted') if s_data else None
            eps_basic_c = c_data.get('eps_basic') if c_data else None
            eps_diluted_c = c_data.get('eps_diluted') if c_data else None
            cum_eps_basic_s = s_data.get('cumulative_eps_basic') if s_data else None
            cum_eps_diluted_s = s_data.get('cumulative_eps_diluted') if s_data else None
            cum_eps_basic_c = c_data.get('cumulative_eps_basic') if c_data else None
            cum_eps_diluted_c = c_data.get('cumulative_eps_diluted') if c_data else None

            await db.execute("""
                INSERT INTO quarterly_results
                (stock_symbol, company_name, quarter, financial_year, period_ended,
                 eps_basic_standalone, eps_diluted_standalone, eps_basic_consolidated, eps_diluted_consolidated,
                 fy_eps_basic_standalone, fy_eps_diluted_standalone,
                 fy_eps_basic_consolidated, fy_eps_diluted_consolidated,
                 fy_eps_formula_standalone, fy_eps_formula_consolidated,
                 cumulative_eps_basic_standalone, cumulative_eps_diluted_standalone,
                 cumulative_eps_basic_consolidated, cumulative_eps_diluted_consolidated,
                 standalone_data, consolidated_data, raw_ai_response,
                 source_pdf_url, source_message_id, exchange, units, stock_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stock_symbol, quarter, financial_year)
                DO UPDATE SET
                    company_name = excluded.company_name,
                    period_ended = excluded.period_ended,
                    eps_basic_standalone = excluded.eps_basic_standalone,
                    eps_diluted_standalone = excluded.eps_diluted_standalone,
                    eps_basic_consolidated = excluded.eps_basic_consolidated,
                    eps_diluted_consolidated = excluded.eps_diluted_consolidated,
                    fy_eps_basic_standalone = excluded.fy_eps_basic_standalone,
                    fy_eps_diluted_standalone = excluded.fy_eps_diluted_standalone,
                    fy_eps_basic_consolidated = excluded.fy_eps_basic_consolidated,
                    fy_eps_diluted_consolidated = excluded.fy_eps_diluted_consolidated,
                    fy_eps_formula_standalone = excluded.fy_eps_formula_standalone,
                    fy_eps_formula_consolidated = excluded.fy_eps_formula_consolidated,
                    cumulative_eps_basic_standalone = excluded.cumulative_eps_basic_standalone,
                    cumulative_eps_diluted_standalone = excluded.cumulative_eps_diluted_standalone,
                    cumulative_eps_basic_consolidated = excluded.cumulative_eps_basic_consolidated,
                    cumulative_eps_diluted_consolidated = excluded.cumulative_eps_diluted_consolidated,
                    standalone_data = excluded.standalone_data,
                    consolidated_data = excluded.consolidated_data,
                    raw_ai_response = excluded.raw_ai_response,
                    units = excluded.units,
                    stock_id = excluded.stock_id,
                    updated_at = excluded.updated_at
            """, (
                symbol, company_name, quarter, fy, data["period_ended"],
                eps_basic_s, eps_diluted_s, eps_basic_c, eps_diluted_c,
                fy_basic_s, fy_diluted_s, fy_basic_c, fy_diluted_c,
                fy_formula_s, fy_formula_c,
                cum_eps_basic_s, cum_eps_diluted_s, cum_eps_basic_c, cum_eps_diluted_c,
                json.dumps(s_data) if s_data else None,
                json.dumps(c_data) if c_data else None,
                json.dumps(ai_response) if not stored else None,
                pdf_path, None, exchange, units, stock_id,
                now_iso, now_iso
            ))
            stored.append(f"{quarter}/{fy}")
        await db.commit()

    print(f"  Stored {len(stored)} periods: {', '.join(stored)}")
    return stored


_nse_token_cache = {}

async def fetch_nse_token_map():
    """Fetch nse_cm_neo sheet -> {SYMBOL: exchange_token}. Cached."""
    global _nse_token_cache
    if _nse_token_cache:
        return _nse_token_cache
    sheet_id = os.getenv("sheet_id", "1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM")
    gid = "1765483913"
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                csv_text = await resp.text()
        df = pd.read_csv(pd.io.common.StringIO(csv_text))
        for _, row in df.iterrows():
            sym_name = row.get("pSymbolName")
            token = row.get("pSymbol")
            if not sym_name or pd.isna(token):
                continue
            clean_sym = str(sym_name).split("-")[0].strip().upper()
            try:
                _nse_token_cache[clean_sym] = int(float(token))
            except (ValueError, TypeError):
                continue
        print(f"  Loaded {len(_nse_token_cache)} symbol→token mappings")
    except Exception as e:
        print(f"  Error fetching token map: {e}")
    return _nse_token_cache


async def fetch_cmp_and_store_pe(symbol, fy_eps_value):
    """Fetch live CMP for symbol via Kotak API, compute PE, store in DB."""
    if not fy_eps_value or fy_eps_value <= 0:
        print(f"  Skipping CMP fetch: FY EPS is {fy_eps_value} (needs positive value for PE)")
        return None, None

    try:
        token_map = await fetch_nse_token_map()
        token = token_map.get(symbol)
        if not token:
            print(f"  No exchange token found for {symbol} — CMP not fetched")
            return None, None

        from get_quote import get_quotes_with_rate_limit, flatten_quote_result_list
        sym_str = f"nse_cm|{token}"
        raw_results = await get_quotes_with_rate_limit([sym_str], requests_per_minute=190)
        flattened = await flatten_quote_result_list(raw_results)

        cmp = None
        for q in flattened:
            if q.get("error"):
                continue
            close_price = q.get("ohlc", {}).get("close")
            if close_price:
                cmp_raw = float(close_price)
                cmp = cmp_raw / 100 if cmp_raw > 100000 else cmp_raw
                break

        if not cmp:
            print(f"  CMP not available from Kotak API for {symbol}")
            return None, None

        pe = round(cmp / fy_eps_value, 2)
        now_iso = datetime.now(IST).isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE quarterly_results SET cmp = ?, pe = ?, cmp_updated_at = ?
                   WHERE id = (
                       SELECT id FROM quarterly_results
                       WHERE stock_symbol = ? AND quarter != 'FY'
                       ORDER BY financial_year DESC, quarter DESC LIMIT 1
                   )""",
                (cmp, pe, now_iso, symbol)
            )
            await db.commit()

        print(f"  CMP: ₹{cmp:.2f} | PE: {pe:.2f} — stored in DB")
        return cmp, pe

    except Exception as e:
        print(f"  CMP fetch error: {e}")
        return None, None


async def main():
    if len(sys.argv) < 3:
        print("Usage: python test_pymupdf_speed.py <pdf_path> SYMBOL [--exchange NSE|BSE] [--no-cmp]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    symbol = sys.argv[2].strip().upper()
    exchange = "NSE"
    skip_cmp = False
    for i, arg in enumerate(sys.argv[3:], 3):
        if arg == "--exchange" and i + 1 < len(sys.argv):
            exchange = sys.argv[i + 1].upper()
        if arg == "--no-cmp":
            skip_cmp = True

    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"PDF: {os.path.basename(pdf_path)} | Symbol: {symbol} | Exchange: {exchange}")
    print(f"{'='*60}")

    # --- STEP 1: PyMuPDF text extraction ---
    print(f"\n[STEP 1] PyMuPDF text extraction...")
    t0 = time.time()
    pages = extract_text_pymupdf(pdf_path)
    text_time = time.time() - t0
    text_pages = sum(1 for p in pages if p["has_text"])
    print(f"  {len(pages)} pages, {text_pages} with text | Time: {text_time*1000:.0f}ms")

    # --- STEP 2: Find financial pages ---
    print(f"\n[STEP 2] Finding financial pages...")
    t0 = time.time()
    if text_pages > 0:
        financial_page_nums = find_financial_pages(pages)
        if not financial_page_nums and text_pages < len(pages):
            print("  Text extraction found no financial pages, trying image fallback...")
            financial_page_nums = find_financial_pages_image_fallback(pdf_path, len(pages))
    else:
        print("  No text layer found — image-based PDF")
        financial_page_nums = find_financial_pages_image_fallback(pdf_path, len(pages))
    filter_time = time.time() - t0
    print(f"  Financial pages: {financial_page_nums} | Time: {filter_time*1000:.0f}ms")

    if not financial_page_nums:
        print("\nNo financial pages detected!")
        sys.exit(1)

    # --- STEP 3: Render financial pages to PNG ---
    print(f"\n[STEP 3] Rendering {len(financial_page_nums)} page(s) to PNG (150 DPI)...")
    t0 = time.time()
    encoded_images = []
    for pn in financial_page_nums:
        png_bytes = render_page_to_png(pdf_path, pn, dpi=150)
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        encoded_images.append(b64)
        print(f"  Page {pn}: {len(png_bytes)/1024:.0f} KB")
    render_time = time.time() - t0
    print(f"  Render time: {render_time*1000:.0f}ms")

    # --- STEP 4: Single OpenAI call ---
    print(f"\n[STEP 4] OpenAI Vision extraction ({len(encoded_images)} images in 1 call)...")
    t0 = time.time()
    result = await call_openai_vision(encoded_images)
    ai_time = time.time() - t0

    # --- RESULTS ---
    standalone = result.get("standalone_periods", [])
    consolidated = result.get("consolidated_periods", [])
    print(f"\n{'='*60}")
    print(f"RESULTS: {result.get('company_name', 'Unknown')}")
    print(f"  Units: {result.get('units', '?')}")
    s_qtr = [p for p in standalone if p.get("period_type") == "quarter"]
    s_cum = [p for p in standalone if p.get("period_type") in ("six_month", "nine_month")]
    s_ann = [p for p in standalone if p.get("period_type") == "annual"]
    c_qtr = [p for p in consolidated if p.get("period_type") == "quarter"]
    c_cum = [p for p in consolidated if p.get("period_type") in ("six_month", "nine_month")]
    c_ann = [p for p in consolidated if p.get("period_type") == "annual"]
    print(f"  Standalone: {len(s_qtr)} quarterly + {len(s_cum)} cumulative + {len(s_ann)} annual = {len(standalone)} total")
    print(f"  Consolidated: {len(c_qtr)} quarterly + {len(c_cum)} cumulative + {len(c_ann)} annual = {len(consolidated)} total")

    # --- FY EPS ---
    fy_eps = compute_all_fy_eps(result)
    print_fy_eps_summary(fy_eps, symbol, result)

    best = fy_eps["consolidated_diluted"] if fy_eps["consolidated_diluted"].get("value") else \
           fy_eps["consolidated_basic"] if fy_eps["consolidated_basic"].get("value") else \
           fy_eps["standalone_diluted"] if fy_eps["standalone_diluted"].get("value") else \
           fy_eps["standalone_basic"]

    best_eps_val = best.get("value")
    if best_eps_val:
        basis = "Consolidated" if "consolidated" in [k for k, v in fy_eps.items() if v is best][0] else "Standalone"
        print(f"\n  >> Best FY EPS (Est.): {best_eps_val:.2f} [{best['formula']}] ({basis})")
    else:
        print(f"\n  >> FY EPS: Could not compute (no EPS data in extraction)")

    # --- STEP 5: Store in DB ---
    print(f"\n[STEP 5] Storing quarterly results in DB ({DB_PATH})...")
    t0 = time.time()
    stored = await store_quarterly_results(result, symbol, exchange, pdf_path)
    db_time = time.time() - t0
    print(f"  DB store time: {db_time*1000:.0f}ms")

    # --- STEP 6: Fetch CMP + compute PE ---
    cmp_time = 0
    if not skip_cmp and stored:
        print(f"\n[STEP 6] Fetching CMP & computing PE...")
        t0 = time.time()
        cmp, pe = await fetch_cmp_and_store_pe(symbol, best_eps_val)
        cmp_time = time.time() - t0
        print(f"  CMP fetch time: {cmp_time*1000:.0f}ms")
    elif skip_cmp:
        print(f"\n[STEP 6] Skipped (--no-cmp)")

    total = text_time + filter_time + render_time + ai_time + db_time + cmp_time
    print(f"\n{'='*60}")
    print(f"TIMING BREAKDOWN:")
    print(f"  Text extraction:  {text_time*1000:>8.0f}ms")
    print(f"  Page filtering:   {filter_time*1000:>8.0f}ms")
    print(f"  PNG rendering:    {render_time*1000:>8.0f}ms")
    print(f"  OpenAI Vision:    {ai_time*1000:>8.0f}ms")
    print(f"  DB storage:       {db_time*1000:>8.0f}ms")
    print(f"  CMP fetch:        {cmp_time*1000:>8.0f}ms")
    print(f"  TOTAL:            {total*1000:>8.0f}ms ({total:.1f}s)")
    print(f"{'='*60}")

    print(f"\nFull JSON output:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
