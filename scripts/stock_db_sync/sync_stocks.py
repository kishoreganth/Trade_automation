"""
Stock DB Sync — Master orchestrator
====================================
Reads Truedata CSVs + Excel sector file, compares with the current database,
and produces a dry-run report.  Pass --apply to execute changes.

Usage:
  # From project root:
  python -m scripts.stock_db_sync.sync_stocks                          # dry-run
  python -m scripts.stock_db_sync.sync_stocks --apply                  # apply changes
  python -m scripts.stock_db_sync.sync_stocks --sql-file output.sql    # export SQL only

Data file locations (override with env vars):
  TRUEDATA_NSE_CSV   default: ~/Downloads/truedata_nse_stocks.csv
  TRUEDATA_BSE_CSV   default: ~/Downloads/truedata_bse_stocks.csv
  SECTOR_EXCEL       default: ~/Downloads/BSE_54Sector OVERALL.xlsx
"""

import argparse
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from .data_loader import build_canonical_map
from .merger import compute_diff
from .db_operations import fetch_db_stocks, generate_all_sql, apply_to_db
from .report import generate_report


def _resolve_path(env_var: str, default: str) -> Path:
    raw = os.environ.get(env_var, default)
    p = Path(raw).expanduser()
    if not p.exists():
        print(f"ERROR: {env_var}={p} not found")
        sys.exit(1)
    return p


def _get_dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "automation_trade")
    user = os.environ.get("POSTGRES_USER", "trade_user")
    pwd = os.environ.get("POSTGRES_PASSWORD", "trade_secure_pwd_2026")
    return f"host={host} port={port} dbname={db} user={user} password={pwd}"


def main():
    parser = argparse.ArgumentParser(description="Stock DB Sync")
    parser.add_argument("--apply", action="store_true", help="Apply changes to the database")
    parser.add_argument("--sql-file", type=str, help="Write generated SQL to file instead of applying")
    args = parser.parse_args()

    downloads = Path.home() / "Downloads"

    nse_csv = _resolve_path("TRUEDATA_NSE_CSV", str(downloads / "truedata_nse_stocks.csv"))
    bse_csv = _resolve_path("TRUEDATA_BSE_CSV", str(downloads / "truedata_bse_stocks.csv"))
    excel_path = _resolve_path("SECTOR_EXCEL", str(downloads / "BSE_54Sector OVERALL.xlsx"))

    print(f"Loading data sources...")
    print(f"  NSE CSV:  {nse_csv}")
    print(f"  BSE CSV:  {bse_csv}")
    print(f"  Excel:    {excel_path}")

    canonical = build_canonical_map(nse_csv, bse_csv, excel_path)
    print(f"  Canonical stocks built: {len(canonical)}")

    dsn = _get_dsn()
    print(f"\nFetching current DB stocks...")
    db_rows = fetch_db_stocks(dsn)
    print(f"  DB rows: {len(db_rows)}")

    print(f"\nComputing diff...")
    diff = compute_diff(canonical, db_rows)

    report_text = generate_report(diff)
    print("\n" + report_text)

    # Save report
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    report_file = output_dir / "sync_report.txt"
    report_file.write_text(report_text, encoding="utf-8")
    print(f"\nReport saved to: {report_file}")

    if args.sql_file:
        sql = generate_all_sql(diff)
        sql_path = Path(args.sql_file)
        sql_path.write_text(sql, encoding="utf-8")
        print(f"SQL saved to: {sql_path}")
        return

    if args.apply:
        print("\n*** APPLYING CHANGES ***")
        summary = apply_to_db(diff, dsn)
        print(f"\nDone!")
        print(f"  Merges applied:  {summary['merges']}")
        print(f"  Updates applied: {summary['updates']}")
        print(f"  Inserts applied: {summary['inserts']}")
        if summary["errors"]:
            print(f"  Insert errors:   {len(summary['errors'])}")
            for err in summary["errors"][:10]:
                print(f"    - {err}")

        # Post-apply validation
        print("\n--- Post-Apply Validation ---")
        post_rows = fetch_db_stocks(dsn)
        print(f"  Total stocks:          {len(post_rows)}")
        print(f"  With ISIN:             {sum(1 for r in post_rows if r.get('isin'))}")
        print(f"  With sector:           {sum(1 for r in post_rows if r.get('sector'))}")
        print(f"  With market_segment:   {sum(1 for r in post_rows if r.get('market_segment'))}")
        print(f"  With nse_series:       {sum(1 for r in post_rows if r.get('nse_series'))}")
        print(f"  With bse_series:       {sum(1 for r in post_rows if r.get('bse_series'))}")
        print(f"  NSE_EQ:                {sum(1 for r in post_rows if r.get('market_segment') == 'NSE_EQ')}")
        print(f"  NSE_SME:               {sum(1 for r in post_rows if r.get('market_segment') == 'NSE_SME')}")
        print(f"  BSE_EQ:                {sum(1 for r in post_rows if r.get('market_segment') == 'BSE_EQ')}")
        print(f"  BSE_SME:               {sum(1 for r in post_rows if r.get('market_segment') == 'BSE_SME')}")
    else:
        print("\nDry-run complete. Use --apply to execute changes.")


if __name__ == "__main__":
    main()
