"""
Step 3B: Fuzzy match BSE-only stocks by company name.
Run this ON THE SERVER where db_stocks_export.csv is available.

Usage:
  python scripts/step3b_fuzzy_match.py

Requires:
  - db_stocks_export.csv in the same directory (from: docker exec trade_postgres psql ...)
  - BSE_54Sector OVERALL.xlsx in project root

Outputs:
  - scripts/output/step3b_fuzzy_matches.csv (all candidates for review)
  - scripts/output/step3b_high_confidence.sql (auto-apply for >90% matches)
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

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
EXCEL_PATH = PROJECT_ROOT / "BSE_54Sector OVERALL.xlsx"
OUTPUT_DIR = SCRIPT_DIR / "output"
DB_EXPORT = Path("db_stocks_export.csv")

if not DB_EXPORT.exists():
    DB_EXPORT = SCRIPT_DIR / "output" / "db_stocks_export.csv"
if not DB_EXPORT.exists():
    DB_EXPORT = PROJECT_ROOT / "db_stocks_export.csv"

COL_COMPANY = 1
COL_BSE_CODE = 2
COL_NSE_CODE = 3
COL_ISIN = 4


def normalize_name(name: str) -> str:
    if not name:
        return ""
    n = name.upper().strip()
    for suffix in [" LIMITED", " LTD.", " LTD", " PRIVATE", " PVT.", " PVT",
                   " CORPORATION", " CORP.", " CORP", " INDUSTRIES", " IND.",
                   " AND ", " & ", "-$"]:
        n = n.replace(suffix, " ")
    n = "".join(c for c in n if c.isalnum() or c == " ")
    return " ".join(n.split())


def similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def escape_sql(val):
    if val is None:
        return "NULL"
    s = str(val).replace("'", "''")
    return f"'{s}'"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_EXPORT.exists():
        print(f"ERROR: db_stocks_export.csv not found.")
        print(f"Run on server:")
        print(f'  docker exec trade_postgres psql -U trade_user -d automation_trade \\')
        print(f'    -c "COPY (SELECT symbol, company_name FROM stocks) TO STDOUT WITH CSV HEADER" \\')
        print(f'    > db_stocks_export.csv')
        sys.exit(1)

    if not EXCEL_PATH.exists():
        print(f"ERROR: Excel file not found at {EXCEL_PATH}")
        sys.exit(1)

    # Read DB stocks (skip numeric symbols - handled by Step 3A)
    print(f"Reading DB export: {DB_EXPORT}")
    db_stocks = {}
    with open(DB_EXPORT, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"]
            if symbol.isdigit():
                continue
            db_stocks[symbol] = row["company_name"] or ""
    print(f"  Loaded {len(db_stocks)} non-numeric DB stocks")

    # Read Excel BSE-only stocks
    print(f"Reading Excel: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
    ws = wb["MASTER DATABASE"]

    bse_only = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[COL_COMPANY]:
            continue
        if row[COL_NSE_CODE]:
            continue
        if not row[COL_BSE_CODE]:
            continue
        bse_only.append({
            "company_name": str(row[COL_COMPANY]).strip(),
            "bse_code": int(row[COL_BSE_CODE]),
            "isin": str(row[COL_ISIN]).strip().upper() if row[COL_ISIN] else None,
        })
    wb.close()
    print(f"  {len(bse_only)} BSE-only stocks to fuzzy match")

    # Fuzzy matching
    high_confidence = []
    low_confidence = []
    no_match_count = 0

    for i, excel_stock in enumerate(bse_only):
        if (i + 1) % 200 == 0:
            print(f"  Processing {i+1}/{len(bse_only)}...")

        best_score = 0.0
        best_symbol = None
        best_name = None

        for db_symbol, db_name in db_stocks.items():
            score = similarity(excel_stock["company_name"], db_name)
            if score > best_score:
                best_score = score
                best_symbol = db_symbol
                best_name = db_name
            if score >= 0.95:
                break

        if best_score >= 0.90:
            high_confidence.append({
                "excel_company": excel_stock["company_name"],
                "excel_bse_code": excel_stock["bse_code"],
                "excel_isin": excel_stock["isin"],
                "db_symbol": best_symbol,
                "db_company": best_name,
                "similarity": round(best_score * 100, 1),
            })
        elif best_score >= 0.70:
            low_confidence.append({
                "excel_company": excel_stock["company_name"],
                "excel_bse_code": excel_stock["bse_code"],
                "excel_isin": excel_stock["isin"],
                "db_symbol": best_symbol,
                "db_company": best_name,
                "similarity": round(best_score * 100, 1),
            })
        else:
            no_match_count += 1

    print(f"\n  Results:")
    print(f"    High confidence (>90%): {len(high_confidence)}")
    print(f"    Low confidence (70-90%): {len(low_confidence)}")
    print(f"    No match (<70%): {no_match_count}")

    # Write CSV for review
    all_matches = high_confidence + low_confidence
    if all_matches:
        csv_file = OUTPUT_DIR / "step3b_fuzzy_matches.csv"
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_matches[0].keys()))
            writer.writeheader()
            writer.writerows(all_matches)
        print(f"  Review CSV: {csv_file}")

    # Generate SQL for high-confidence
    sql_lines = [
        "-- Step 3B: High-confidence fuzzy matches (>90% company name similarity)",
        "-- BSE-only stocks matched to DB by normalized company name.",
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
        sql_lines.append(
            f"-- {entry['excel_company']} -> {entry['db_company']} ({entry['similarity']}%)"
        )
        sql_lines.append(
            f"UPDATE stocks SET {set_clause} WHERE symbol = {escape_sql(entry['db_symbol'])};"
        )

    sql_lines.append("")
    sql_lines.append("COMMIT;")
    sql_lines.append(f"-- High confidence matches: {len(high_confidence)}")

    sql_file = OUTPUT_DIR / "step3b_high_confidence.sql"
    sql_file.write_text("\n".join(sql_lines), encoding="utf-8")
    print(f"  SQL file: {sql_file}")
    print(f"\nDone!")


if __name__ == "__main__":
    main()
