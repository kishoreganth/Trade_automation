"""
Diagnose and fix wrong symbol <-> company_name mappings in quarterly_results.

Root cause: _scrip_to_symbol() resolved BSE scrip codes to wrong NSE symbols
because stocks.bse_token was incorrectly assigned (bad ISIN join from Truedata CSVs).

Run with --dry-run first, then --apply to fix.

Usage:
    python scripts/fix_symbol_name_mismatch.py --dry-run
    python scripts/fix_symbol_name_mismatch.py --apply
"""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import text
from app.database import get_db_session


DIAGNOSE_MISMATCHED_QR_SQL = """
SELECT
    qr.id,
    qr.stock_symbol,
    qr.company_name AS qr_company,
    s.company_name  AS stocks_company,
    qr.exchange,
    qr.quarter,
    qr.financial_year,
    qr.extraction_status,
    qr.announcement_date
FROM quarterly_results qr
JOIN stocks s ON s.symbol = qr.stock_symbol
WHERE s.company_name IS NOT NULL
  AND qr.company_name IS NOT NULL
  AND s.company_name != ''
  AND qr.company_name != ''
  AND LOWER(s.company_name) NOT LIKE '%' || LOWER(
      SPLIT_PART(SPLIT_PART(qr.company_name, ' Limited', 1), ' Ltd', 1)
  ) || '%'
  AND LOWER(
      SPLIT_PART(SPLIT_PART(qr.company_name, ' Limited', 1), ' Ltd', 1)
  ) NOT LIKE '%' || LOWER(
      SPLIT_PART(SPLIT_PART(s.company_name, ' Limited', 1), ' Ltd', 1)
  ) || '%'
ORDER BY qr.announcement_date DESC
"""

DIAGNOSE_WRONG_BSE_TOKEN_SQL = """
SELECT
    s.id,
    s.symbol,
    s.company_name,
    s.bse_token,
    s.bse_scrip_code,
    s.isin,
    s2.symbol     AS conflicting_symbol,
    s2.company_name AS conflicting_company,
    s2.bse_scrip_code AS conflicting_scrip
FROM stocks s
JOIN stocks s2 ON s2.bse_scrip_code = CAST(s.bse_token AS TEXT)
              AND s2.id != s.id
WHERE s.bse_token IS NOT NULL
ORDER BY s.symbol
"""

FIND_CORRECT_SYMBOL_SQL = """
SELECT symbol, company_name, bse_token, bse_scrip_code
FROM stocks
WHERE bse_token = :bse_token OR bse_scrip_code = :scrip_code
ORDER BY
    CASE WHEN bse_scrip_code = :scrip_code THEN 0 ELSE 1 END,
    id
"""


async def diagnose(apply: bool = False):
    async with get_db_session() as db:
        print("=" * 80)
        print("1. MISMATCHED symbol <-> company_name in quarterly_results")
        print("=" * 80)

        rows = await db.execute(text(DIAGNOSE_MISMATCHED_QR_SQL))
        mismatches = rows.fetchall()

        if not mismatches:
            print("  No mismatches found.\n")
        else:
            print(f"  Found {len(mismatches)} mismatched rows:\n")
            by_symbol: dict[str, list] = {}
            for r in mismatches:
                by_symbol.setdefault(r.stock_symbol, []).append(r)

            for sym, items in sorted(by_symbol.items()):
                print(f"  Symbol: {sym}")
                print(f"    stocks.company_name:  {items[0].stocks_company}")
                print(f"    qr.company_name:      {items[0].qr_company}")
                print(f"    Affected rows:        {len(items)}")
                print()

        print("=" * 80)
        print("2. WRONG bse_token in stocks (token points to different stock)")
        print("=" * 80)

        rows = await db.execute(text(DIAGNOSE_WRONG_BSE_TOKEN_SQL))
        conflicts = rows.fetchall()

        if not conflicts:
            print("  No bse_token conflicts found.\n")
        else:
            print(f"  Found {len(conflicts)} conflicts:\n")
            for r in conflicts:
                print(f"  {r.symbol} (bse_token={r.bse_token}) "
                      f"conflicts with {r.conflicting_symbol} "
                      f"(bse_scrip_code={r.conflicting_scrip})")
            print()

        print("=" * 80)
        print("3. DUPLICATE bse_token values (multiple stocks sharing same token)")
        print("=" * 80)

        rows = await db.execute(text("""
            SELECT bse_token, ARRAY_AGG(symbol) AS symbols,
                   ARRAY_AGG(company_name) AS names
            FROM stocks
            WHERE bse_token IS NOT NULL
            GROUP BY bse_token
            HAVING COUNT(*) > 1
            ORDER BY bse_token
        """))
        dupes = rows.fetchall()

        if not dupes:
            print("  No duplicate bse_token values.\n")
        else:
            print(f"  Found {len(dupes)} duplicate bse_token groups:\n")
            for r in dupes:
                print(f"  bse_token={r.bse_token}: {r.symbols} -> {r.names}")
            print()

        if not apply:
            print("Run with --apply to fix the quarterly_results rows.")
            return

        if not mismatches:
            print("Nothing to fix.")
            return

        print("=" * 80)
        print("APPLYING FIXES")
        print("=" * 80)

        fixed = 0
        for sym, items in by_symbol.items():
            qr_company = items[0].qr_company
            clean = qr_company.split(" Limited")[0].split(" Ltd")[0].strip()

            # Find the correct symbol for this company
            row = await db.execute(text(
                "SELECT symbol FROM stocks "
                "WHERE company_name ILIKE :pattern "
                "ORDER BY LENGTH(company_name) ASC LIMIT 1"
            ), {"pattern": f"{clean}%"})
            correct_symbol = row.scalar()

            if correct_symbol and correct_symbol != sym:
                ids = [r.id for r in items]
                print(f"  Fixing {len(ids)} rows: {sym} -> {correct_symbol} ({qr_company})")
                await db.execute(text(
                    "UPDATE quarterly_results SET stock_symbol = :new_sym "
                    "WHERE id = ANY(:ids)"
                ), {"new_sym": correct_symbol, "ids": ids})
                fixed += len(ids)
            else:
                print(f"  SKIP {sym} ({qr_company}): no correct symbol found "
                      f"(match={correct_symbol})")

        if fixed:
            await db.commit()
            print(f"\n  Fixed {fixed} rows total.")
        else:
            print("\n  No rows fixed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Apply fixes (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()
    asyncio.run(diagnose(apply=args.apply))
