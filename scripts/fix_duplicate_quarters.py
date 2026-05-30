"""
Fix duplicate quarterly_results rows: keep only the current quarter per announcement.

Usage:
  python scripts/fix_duplicate_quarters.py report     # Show what would be cleaned (no changes)
  python scripts/fix_duplicate_quarters.py cleanup     # Actually delete duplicates

Requires DATABASE_URL env var or .env file in project root.
"""

import asyncio
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add backend to path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "backend"))
os.environ.setdefault("CELERY_WORKER", "")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[0].parent / ".env")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

_IST = timezone(timedelta(hours=5, minutes=30))
_QUARTER_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "automation_trade")
    user = os.getenv("POSTGRES_USER", "trade_user")
    pwd = os.getenv("POSTGRES_PASSWORD", "trade_secure_pwd_2026")
    return f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{db}"


def _fy_sort_key(fy: str) -> int:
    if not fy:
        return 0
    m = re.match(r"(\d{4})-(\d{2})$", fy)
    if m:
        return 2000 + int(m.group(2))
    m = re.match(r"(\d{4})$", fy)
    if m:
        return int(m.group(1))
    return 0


def _expected_quarter(ann_date) -> tuple:
    """Derive expected (quarter, fy) from announcement date using Indian FY calendar."""
    if ann_date is None:
        return None, None
    if isinstance(ann_date, str):
        try:
            ann_date = datetime.fromisoformat(ann_date)
        except Exception:
            return None, None
    y, m = ann_date.year, ann_date.month
    if 4 <= m <= 6:
        return "Q4", f"{y - 1}-{str(y)[-2:]}"
    if 7 <= m <= 9:
        return "Q1", f"{y}-{str(y + 1)[-2:]}"
    if 10 <= m <= 12:
        return "Q2", f"{y}-{str(y + 1)[-2:]}"
    return "Q3", f"{y - 1}-{str(y)[-2:]}"


def _pick_best_row(rows: list) -> int:
    """Given multiple rows for the same (stock, pdf), return the ID to KEEP."""
    exp_q, exp_fy = _expected_quarter(rows[0]["announcement_date"])

    # Priority 1: exact match on expected quarter
    if exp_q and exp_fy:
        for r in rows:
            if r["quarter"] == exp_q and r["financial_year"] == exp_fy:
                return r["id"]

    # Priority 2: latest by FY calendar (exclude FY/annual rows)
    quarterly = [r for r in rows if r["quarter"] in _QUARTER_ORDER]
    if quarterly:
        best = max(quarterly, key=lambda r: (
            _fy_sort_key(r["financial_year"]),
            _QUARTER_ORDER.get(r["quarter"], 0),
        ))
        return best["id"]

    # Priority 3: just keep the latest row by ID
    return max(r["id"] for r in rows)


async def run(mode: str):
    url = _get_database_url()
    engine = create_async_engine(url, pool_size=2)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        # Find all (stock_symbol, source_pdf_url) groups with >1 row
        result = await db.execute(text("""
            SELECT stock_symbol, source_pdf_url, COUNT(*) as cnt
            FROM quarterly_results
            WHERE extraction_status = 'completed'
              AND source_pdf_url IS NOT NULL
              AND source_pdf_url <> ''
            GROUP BY stock_symbol, source_pdf_url
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
        """))
        groups = [dict(r._mapping) for r in result.fetchall()]

        if not groups:
            print("\nNo duplicates found. All stocks have 1 row per announcement.")
            await engine.dispose()
            return

        # Fetch all rows for these groups
        total_rows = 0
        total_to_delete = 0
        total_to_keep = 0
        details = []

        for g in groups:
            sym = g["stock_symbol"]
            pdf = g["source_pdf_url"]

            result = await db.execute(text("""
                SELECT id, stock_symbol, quarter, financial_year,
                       announcement_date, period_ended, extraction_status,
                       eps_basic_standalone, eps_diluted_standalone,
                       eps_basic_consolidated, eps_diluted_consolidated
                FROM quarterly_results
                WHERE stock_symbol = :sym AND source_pdf_url = :pdf
                  AND extraction_status = 'completed'
                ORDER BY id
            """), {"sym": sym, "pdf": pdf})
            rows = [dict(r._mapping) for r in result.fetchall()]

            if len(rows) <= 1:
                continue

            keep_id = _pick_best_row(rows)
            delete_ids = [r["id"] for r in rows if r["id"] != keep_id]
            keep_row = next(r for r in rows if r["id"] == keep_id)

            total_rows += len(rows)
            total_to_keep += 1
            total_to_delete += len(delete_ids)

            details.append({
                "symbol": sym,
                "total_rows": len(rows),
                "keep": f"{keep_row['quarter']} {keep_row['financial_year']} (id={keep_id})",
                "delete_count": len(delete_ids),
                "delete_ids": delete_ids,
                "quarters": [f"{r['quarter']} {r['financial_year']}" for r in rows],
            })

        # --- REPORT ---
        print(f"\n{'='*70}")
        print(f"  QUARTERLY RESULTS DUPLICATE REPORT")
        print(f"{'='*70}")
        print(f"  Stocks with duplicates : {len(details)}")
        print(f"  Total duplicate rows   : {total_rows}")
        print(f"  Rows to KEEP           : {total_to_keep}")
        print(f"  Rows to DELETE         : {total_to_delete}")
        print(f"{'='*70}\n")

        # Quarter distribution of rows to be deleted
        delete_quarter_dist = defaultdict(int)
        keep_quarter_dist = defaultdict(int)
        for d in details:
            keep_q = d["keep"].split(" ")[0]
            keep_quarter_dist[keep_q] += 1
            for q_str in d["quarters"]:
                q = q_str.split(" ")[0]
                if q != keep_q or q_str not in d["keep"]:
                    delete_quarter_dist[q] += 1

        print("  Rows being KEPT by quarter:")
        for q in ("Q1", "Q2", "Q3", "Q4"):
            if keep_quarter_dist.get(q):
                print(f"    {q}: {keep_quarter_dist[q]}")

        print("\n  Rows being DELETED by quarter:")
        for q in ("Q1", "Q2", "Q3", "Q4", "FY"):
            if delete_quarter_dist.get(q):
                print(f"    {q}: {delete_quarter_dist[q]}")

        print(f"\n{'='*70}")
        print(f"  SAMPLE (first 20 stocks)")
        print(f"{'='*70}")
        for d in details[:20]:
            print(f"\n  {d['symbol']} ({d['total_rows']} rows)")
            print(f"    All quarters : {', '.join(d['quarters'])}")
            print(f"    KEEP         : {d['keep']}")
            print(f"    DELETE       : {d['delete_count']} rows (ids: {d['delete_ids']})")

        if len(details) > 20:
            print(f"\n  ... and {len(details) - 20} more stocks")

        # --- CLEANUP ---
        if mode == "cleanup":
            print(f"\n{'='*70}")
            print(f"  EXECUTING CLEANUP...")
            print(f"{'='*70}")

            all_delete_ids = []
            for d in details:
                all_delete_ids.extend(d["delete_ids"])

            if all_delete_ids:
                await db.execute(text("""
                    DELETE FROM quarterly_results
                    WHERE id = ANY(:ids)
                """), {"ids": all_delete_ids})
                await db.commit()
                print(f"\n  DELETED {len(all_delete_ids)} duplicate rows.")
                print(f"  KEPT {total_to_keep} current-quarter rows.")
            else:
                print("\n  Nothing to delete.")
        else:
            print(f"\n  This was a DRY RUN (report mode).")
            print(f"  Run with 'cleanup' to actually delete duplicates:")
            print(f"  python scripts/fix_duplicate_quarters.py cleanup")

        print(f"\n{'='*70}\n")

    await engine.dispose()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("report", "cleanup"):
        print("Usage:")
        print("  python scripts/fix_duplicate_quarters.py report   # Preview (no changes)")
        print("  python scripts/fix_duplicate_quarters.py cleanup  # Delete duplicates")
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "cleanup":
        confirm = input("\nThis will DELETE duplicate rows from quarterly_results. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    asyncio.run(run(mode))


if __name__ == "__main__":
    main()
