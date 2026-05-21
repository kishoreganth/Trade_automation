"""
Stock Identity Enrichment Script
=================================
Reads BSE_54Sector OVERALL.xlsx and generates SQL to:
  Step 1: UPDATE existing DB stocks with bse_token + isin (matched by NSE Code -> symbol)
  Step 2: INSERT new stocks that have NSE codes but don't exist in DB
  Step 3: Fuzzy match BSE-only stocks by company name (requires DB export)

Usage:
  python scripts/enrich_stocks_from_excel.py

Outputs:
  - scripts/output/step1_update_identity.sql   (UPDATE bse_token, isin for matched stocks)
  - scripts/output/step2_insert_new_nse.sql    (INSERT stocks with NSE code not in DB)
  - scripts/output/step3_fuzzy_matches.csv     (fuzzy match candidates for review)
  - scripts/output/step3_high_confidence.sql   (auto-apply SQL for >90% matches)
  - scripts/output/dry_run_report.txt          (summary of what will happen)

NOTE: Sector is NOT touched. Only bse_token and isin are updated for existing stocks.
      New inserts (Step 2) will include sector from Excel since no DB data exists for them.
"""

import os
import sys
import csv
from pathlib import Path
from difflib import SequenceMatcher

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip install openpyxl")
    sys.exit(1)


EXCEL_PATH = Path(__file__).parent.parent / "BSE_54Sector OVERALL.xlsx"
OUTPUT_DIR = Path(__file__).parent / "output"
DB_STOCKS_EXPORT = Path(__file__).parent / "output" / "db_stocks_export.csv"

# Columns in MASTER DATABASE sheet (0-indexed):
COL_COMPANY = 1
COL_BSE_CODE = 2
COL_NSE_CODE = 3
COL_ISIN = 4
COL_SECTOR = 5
COL_INDUSTRY_GROUP = 6
COL_SUB_INDUSTRY = 8
COL_EXCHANGE_LISTED = 10


def normalize_name(name: str) -> str:
    """Normalize company name for fuzzy matching."""
    if not name:
        return ""
    n = name.upper().strip()
    for suffix in [" LIMITED", " LTD.", " LTD", " PRIVATE", " PVT.", " PVT",
                   " CORPORATION", " CORP.", " CORP", " INDUSTRIES", " IND."]:
        n = n.replace(suffix, "")
    n = "".join(c for c in n if c.isalnum() or c == " ")
    return " ".join(n.split())


def similarity(a: str, b: str) -> float:
    """Return similarity ratio between two strings (0-1)."""
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def read_excel():
    """Read MASTER DATABASE sheet and return structured data."""
    print(f"Reading Excel: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
    ws = wb["MASTER DATABASE"]

    stocks = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[COL_COMPANY]:
            continue
        stocks.append({
            "company_name": str(row[COL_COMPANY]).strip(),
            "bse_code": int(row[COL_BSE_CODE]) if row[COL_BSE_CODE] else None,
            "nse_code": str(row[COL_NSE_CODE]).strip().upper() if row[COL_NSE_CODE] else None,
            "isin": str(row[COL_ISIN]).strip().upper() if row[COL_ISIN] else None,
            "sector": str(row[COL_SECTOR]).strip() if row[COL_SECTOR] else None,
            "industry_group": str(row[COL_INDUSTRY_GROUP]).strip() if row[COL_INDUSTRY_GROUP] else None,
            "sub_industry": str(row[COL_SUB_INDUSTRY]).strip() if row[COL_SUB_INDUSTRY] else None,
            "exchange_listed": str(row[COL_EXCHANGE_LISTED]).strip() if row[COL_EXCHANGE_LISTED] else None,
        })

    wb.close()
    print(f"  Read {len(stocks)} stocks from Excel")
    return stocks


def escape_sql(val):
    """Escape a value for SQL."""
    if val is None:
        return "NULL"
    s = str(val).replace("'", "''")
    return f"'{s}'"


def generate_step1(excel_stocks):
    """Step 1: UPDATE bse_token + isin for stocks matching by NSE Code."""
    nse_stocks = [s for s in excel_stocks if s["nse_code"]]
    print(f"\nStep 1: {len(nse_stocks)} Excel stocks have NSE codes")

    sql_lines = [
        "-- Step 1: Update bse_token and isin for existing stocks (matched by NSE symbol)",
        "-- Only updates identity fields. Does NOT touch sector.",
        "-- Safe: UPDATE WHERE symbol = X only affects rows that exist.",
        "BEGIN;",
        "",
    ]

    count = 0
    for s in nse_stocks:
        parts = []
        if s["bse_code"]:
            parts.append(f"bse_token = {s['bse_code']}")
        if s["isin"]:
            parts.append(f"isin = {escape_sql(s['isin'])}")

        if not parts:
            continue

        parts.append("updated_at = NOW()")
        set_clause = ", ".join(parts)
        sql_lines.append(
            f"UPDATE stocks SET {set_clause} WHERE symbol = {escape_sql(s['nse_code'])};"
        )
        count += 1

    sql_lines.append("")
    sql_lines.append("COMMIT;")
    sql_lines.append(f"-- Total UPDATE statements: {count}")

    output_file = OUTPUT_DIR / "step1_update_identity.sql"
    output_file.write_text("\n".join(sql_lines), encoding="utf-8")
    print(f"  Generated: {output_file} ({count} UPDATE statements)")
    return count


def generate_step2(excel_stocks):
    """Step 2: INSERT stocks that have NSE code but might not exist in DB.
    Uses ON CONFLICT (symbol) DO NOTHING -- safe to run without checking first.
    """
    nse_stocks = [s for s in excel_stocks if s["nse_code"]]
    print(f"\nStep 2: Generating INSERT for {len(nse_stocks)} NSE stocks (ON CONFLICT DO NOTHING)")

    sql_lines = [
        "-- Step 2: Insert new stocks from Excel that don't exist in DB yet",
        "-- Uses ON CONFLICT DO NOTHING -- only inserts if symbol doesn't exist.",
        "-- Includes sector from Excel for NEW stocks only (existing stocks untouched).",
        "BEGIN;",
        "",
    ]

    count = 0
    for s in nse_stocks:
        symbol = escape_sql(s["nse_code"])
        company = escape_sql(s["company_name"])
        bse = s["bse_code"] if s["bse_code"] else "NULL"
        isin = escape_sql(s["isin"])
        sector = escape_sql(s["sector"])
        sub_sector = escape_sql(s["industry_group"])

        sql_lines.append(
            f"INSERT INTO stocks (symbol, company_name, exchange, sector, sub_sector, "
            f"bse_token, isin, is_active, added_at, updated_at) "
            f"VALUES ({symbol}, {company}, 'NSE', {sector}, {sub_sector}, "
            f"{bse}, {isin}, true, NOW(), NOW()) "
            f"ON CONFLICT (symbol) DO NOTHING;"
        )
        count += 1

    sql_lines.append("")
    sql_lines.append("COMMIT;")
    sql_lines.append(f"-- Total INSERT statements: {count}")

    output_file = OUTPUT_DIR / "step2_insert_new_nse.sql"
    output_file.write_text("\n".join(sql_lines), encoding="utf-8")
    print(f"  Generated: {output_file} ({count} INSERT statements)")
    return count


def generate_step3(excel_stocks):
    """Step 3: Match BSE-only stocks against DB.
    Part A: Exact match (Excel BSE Code -> DB symbol stored as BSE code)
    Part B: Fuzzy match by company name (requires db_stocks_export.csv)
    """
    bse_only = [s for s in excel_stocks if not s["nse_code"] and s["bse_code"]]
    print(f"\nStep 3: {len(bse_only)} BSE-only stocks (no NSE code)")

    # --- Part A: Exact match BSE code -> symbol ---
    sql_lines_a = [
        "-- Step 3A: Exact match - Excel BSE Code matches DB symbol (stored as scrip code)",
        "-- Updates bse_token + isin for stocks stored with BSE scrip code as symbol.",
        "-- Safe: UPDATE only affects rows where symbol = BSE code string.",
        "-- Sector: NOT TOUCHED.",
        "BEGIN;",
        "",
    ]

    part_a_count = 0
    part_a_codes = set()
    for s in bse_only:
        bse_str = str(s["bse_code"])
        parts = [f"bse_token = {s['bse_code']}"]
        if s["isin"]:
            parts.append(f"isin = {escape_sql(s['isin'])}")
        parts.append("updated_at = NOW()")
        set_clause = ", ".join(parts)
        sql_lines_a.append(
            f"UPDATE stocks SET {set_clause} WHERE symbol = {escape_sql(bse_str)};"
        )
        part_a_count += 1
        part_a_codes.add(s["bse_code"])

    sql_lines_a.append("")
    sql_lines_a.append("COMMIT;")
    sql_lines_a.append(f"-- Total UPDATE statements: {part_a_count}")

    output_a = OUTPUT_DIR / "step3a_exact_bse_match.sql"
    output_a.write_text("\n".join(sql_lines_a), encoding="utf-8")
    print(f"  Part A (exact BSE code match): {output_a} ({part_a_count} UPDATE statements)")

    # --- Part B: Fuzzy match by company name ---
    if not DB_STOCKS_EXPORT.exists():
        print(f"  Part B SKIPPED: {DB_STOCKS_EXPORT} not found.")
        print(f"  To enable fuzzy matching, copy db_stocks_export.csv from server to:")
        print(f"    {DB_STOCKS_EXPORT}")
        print(f"  Then re-run this script.")
        return part_a_count, 0, 0

    # Read DB stocks
    db_stocks = {}
    with open(DB_STOCKS_EXPORT, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"]
            # Skip DB entries that are numeric (BSE codes) - already handled in Part A
            if symbol.isdigit():
                continue
            db_stocks[symbol] = row["company_name"]

    print(f"  Loaded {len(db_stocks)} non-numeric DB stocks for fuzzy matching")

    # Only fuzzy-match BSE-only stocks that might have an NSE counterpart in DB
    # (i.e., company exists on both exchanges but Excel only has BSE code)
    high_confidence = []
    low_confidence = []
    no_match = []

    for i, excel_stock in enumerate(bse_only):
        if (i + 1) % 200 == 0:
            print(f"  Fuzzy matching {i+1}/{len(bse_only)}...")

        best_match = None
        best_score = 0.0
        best_symbol = None

        excel_norm = normalize_name(excel_stock["company_name"])
        if not excel_norm:
            no_match.append({"excel_company": excel_stock["company_name"],
                           "excel_bse_code": excel_stock["bse_code"],
                           "similarity": 0})
            continue

        for db_symbol, db_name in db_stocks.items():
            score = similarity(excel_stock["company_name"], db_name)
            if score > best_score:
                best_score = score
                best_match = db_name
                best_symbol = db_symbol
            if score >= 0.95:
                break  # Good enough, stop early

        entry = {
            "excel_company": excel_stock["company_name"],
            "excel_bse_code": excel_stock["bse_code"],
            "excel_isin": excel_stock["isin"],
            "db_symbol": best_symbol,
            "db_company": best_match,
            "similarity": round(best_score * 100, 1),
        }

        if best_score >= 0.90:
            high_confidence.append(entry)
        elif best_score >= 0.70:
            low_confidence.append(entry)
        else:
            no_match.append(entry)

    # Write all fuzzy match candidates to CSV for review
    all_matches = high_confidence + low_confidence
    csv_file = OUTPUT_DIR / "step3b_fuzzy_matches.csv"
    if all_matches:
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_matches[0].keys()))
            writer.writeheader()
            writer.writerows(all_matches)
        print(f"  Fuzzy matches CSV: {csv_file} ({len(all_matches)} candidates)")

    # Generate SQL for high-confidence matches
    sql_lines_b = [
        "-- Step 3B: High-confidence fuzzy matches (>90% company name similarity)",
        "-- BSE-only stocks matched to DB stocks by normalized company name.",
        "-- Only updates bse_token and isin. Does NOT touch sector.",
        "BEGIN;",
        "",
    ]

    for entry in high_confidence:
        parts = [f"bse_token = {entry['excel_bse_code']}"]
        if entry["excel_isin"]:
            parts.append(f"isin = {escape_sql(entry['excel_isin'])}")
        parts.append("updated_at = NOW()")
        set_clause = ", ".join(parts)
        sql_lines_b.append(
            f"-- {entry['excel_company']} -> {entry['db_company']} ({entry['similarity']}%)"
        )
        sql_lines_b.append(
            f"UPDATE stocks SET {set_clause} WHERE symbol = {escape_sql(entry['db_symbol'])};"
        )

    sql_lines_b.append("")
    sql_lines_b.append("COMMIT;")
    sql_lines_b.append(f"-- High confidence matches: {len(high_confidence)}")

    sql_file_b = OUTPUT_DIR / "step3b_high_confidence.sql"
    sql_file_b.write_text("\n".join(sql_lines_b), encoding="utf-8")
    print(f"  Part B high-confidence SQL: {sql_file_b} ({len(high_confidence)} matches)")
    print(f"  Part B low-confidence (review): {len(low_confidence)}")
    print(f"  Part B no match: {len(no_match)}")

    return part_a_count, len(high_confidence), len(low_confidence)


def generate_dry_run_report(excel_stocks, step1_count, step2_count, step3a_count, step3b_high, step3b_low):
    """Generate a summary report."""
    nse_stocks = [s for s in excel_stocks if s["nse_code"]]
    bse_only = [s for s in excel_stocks if not s["nse_code"] and s["bse_code"]]

    report = f"""
================================================================================
  STOCK IDENTITY ENRICHMENT - DRY RUN REPORT
================================================================================

  Excel source: BSE_54Sector OVERALL.xlsx (MASTER DATABASE sheet)
  Total Excel stocks: {len(excel_stocks)}
    - With NSE Code: {len(nse_stocks)}
    - BSE-Only (no NSE): {len(bse_only)}

--------------------------------------------------------------------------------
  STEP 1: UPDATE bse_token + isin (match by NSE Code -> DB symbol)
--------------------------------------------------------------------------------
  SQL statements generated: {step1_count}
  What happens: For each Excel stock with an NSE Code, update the matching DB
  row's bse_token and isin. If symbol doesn't exist in DB, UPDATE affects 0 rows.
  Sector: NOT TOUCHED.

--------------------------------------------------------------------------------
  STEP 2: INSERT new NSE stocks not in DB
--------------------------------------------------------------------------------
  SQL statements generated: {step2_count}
  What happens: For each Excel stock with NSE Code, try to INSERT.
  ON CONFLICT (symbol) DO NOTHING -- existing stocks are not affected.
  New stocks get: symbol, company_name, exchange='NSE', sector (from Excel),
  sub_sector, bse_token, isin.

  NOTE: Only stocks that DON'T already exist in DB will be inserted.
  Expected new inserts: likely small number (DB already has 7,296 stocks).

--------------------------------------------------------------------------------
  STEP 3A: Exact BSE code match (Excel BSE Code -> DB symbol as scrip code)
--------------------------------------------------------------------------------
  SQL statements generated: {step3a_count}
  What happens: Many DB stocks are stored with BSE scrip code as their symbol
  (e.g., symbol='500003'). This updates their bse_token + isin directly.
  Sector: NOT TOUCHED.

--------------------------------------------------------------------------------
  STEP 3B: Fuzzy match by company name
--------------------------------------------------------------------------------
  High confidence (>90%, auto-apply): {step3b_high}
  Low confidence (70-90%, needs review): {step3b_low}
  What happens: BSE-only stocks matched to DB by normalized company name.
  Only updates bse_token + isin. Sector: NOT TOUCHED.

--------------------------------------------------------------------------------
  EXECUTION ORDER (on server)
--------------------------------------------------------------------------------
  1. Run step1_update_identity.sql
  2. Run step2_insert_new_nse.sql
  3. Run step3a_exact_bse_match.sql
  4. Review step3b_fuzzy_matches.csv (optional)
  5. Run step3b_high_confidence.sql

  All scripts use BEGIN/COMMIT transactions. Safe to re-run (idempotent).

--------------------------------------------------------------------------------
  HOW TO APPLY ON SERVER
--------------------------------------------------------------------------------
  # Copy output files to server, then:

  docker exec -i trade_postgres psql -U trade_user -d automation_trade \\
    < step1_update_identity.sql

  docker exec -i trade_postgres psql -U trade_user -d automation_trade \\
    < step2_insert_new_nse.sql

  docker exec -i trade_postgres psql -U trade_user -d automation_trade \\
    < step3a_exact_bse_match.sql

  docker exec -i trade_postgres psql -U trade_user -d automation_trade \\
    < step3b_high_confidence.sql

  # Verify after:
  docker exec trade_postgres psql -U trade_user -d automation_trade -c \\
    "SELECT COUNT(*) AS with_bse_token FROM stocks WHERE bse_token IS NOT NULL;"

================================================================================
"""
    output_file = OUTPUT_DIR / "dry_run_report.txt"
    output_file.write_text(report, encoding="utf-8")
    print(f"\n{'='*60}")
    print(report)
    return output_file


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    excel_stocks = read_excel()

    step1_count = generate_step1(excel_stocks)
    step2_count = generate_step2(excel_stocks)
    result = generate_step3(excel_stocks)
    if isinstance(result, tuple) and len(result) == 3:
        step3a_count, step3b_high, step3b_low = result
    elif isinstance(result, tuple) and len(result) == 2:
        step3a_count, step3b_high, step3b_low = result[0], 0, 0
    else:
        step3a_count, step3b_high, step3b_low = 0, 0, 0

    generate_dry_run_report(excel_stocks, step1_count, step2_count, step3a_count, step3b_high, step3b_low)

    print("\nDone! Check scripts/output/ for generated files.")


if __name__ == "__main__":
    main()
