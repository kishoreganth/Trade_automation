"""
Check PE status of stocks from Master_Stocks.xlsx against the Trade Automation DB.
Connects via SSH to the automation server, queries PostgreSQL via docker exec.

Reports: PE Reviewed, PE Pending, Missing.
"""

import asyncio
import json
import sys
from pathlib import Path

import paramiko
import openpyxl


SSH_HOST = "122.165.113.41"
SSH_USER = "kishore"
SSH_PASS = "root"
DB_CONTAINER = "trade_postgres"
DB_NAME = "automation_trade"
DB_USER = "trade_user"


def ssh_exec(client: paramiko.SSHClient, cmd: str) -> str:
    """Execute command via SSH and return stdout."""
    _, stdout, stderr = client.exec_command(cmd, timeout=60)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if stderr.channel.recv_exit_status() != 0 and not out:
        raise RuntimeError(f"Command failed: {err}")
    return out


def load_excel_stocks(filepath: str) -> list[dict]:
    """Load stock symbols from Excel file."""
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    stocks = []
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        sno = row[0].value
        sector = row[1].value
        symbol = row[2].value
        if symbol:
            stocks.append({
                "sno": sno,
                "sector": str(sector).strip() if sector else "",
                "symbol": str(symbol).strip().upper(),
            })
    wb.close()
    return stocks


def run_db_query(client: paramiko.SSHClient, sql: str) -> str:
    """Run a SQL query via docker exec on the postgres container."""
    escaped_sql = sql.replace("'", "'\\''")
    cmd = f"docker exec {DB_CONTAINER} psql -U {DB_USER} -d {DB_NAME} -t -A -F '|' -c '{escaped_sql}'"
    return ssh_exec(client, cmd)


def save_excel_with_status(filepath: str, stocks: list[dict], reviewed_symbols: set, pending_symbols: set):
    """Save a new Excel with PE Status column added."""
    wb = openpyxl.load_workbook(filepath)
    ws = wb.active

    # Add header for new column
    status_col = 5  # Column E
    ws.cell(row=1, column=status_col, value="PE Status")

    from openpyxl.styles import Font, PatternFill
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    green_font = Font(color="006100", bold=True)
    yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    yellow_font = Font(color="9C5700", bold=True)
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    red_font = Font(color="9C0006", bold=True)

    for i, stock in enumerate(stocks, start=2):
        sym = stock["symbol"]
        cell = ws.cell(row=i, column=status_col)
        if sym in reviewed_symbols:
            cell.value = "REVIEWED"
            cell.fill = green_fill
            cell.font = green_font
        elif sym in pending_symbols:
            cell.value = "PENDING"
            cell.fill = yellow_fill
            cell.font = yellow_font
        else:
            cell.value = "NOT FOUND"
            cell.fill = red_fill
            cell.font = red_font

    # Auto-width for status column
    ws.column_dimensions["E"].width = 14

    output_path = filepath.replace(".xlsx", "_PE_Status.xlsx")
    wb.save(output_path)
    wb.close()
    return output_path


def main():
    excel_path = Path(__file__).parent.parent / "Master_Stocks.xlsx"
    if not excel_path.exists():
        print(f"ERROR: {excel_path} not found")
        sys.exit(1)

    print(f"Loading stocks from: {excel_path}")
    stocks = load_excel_stocks(str(excel_path))
    print(f"Total stocks in Excel: {len(stocks)}")

    # Connect SSH
    print(f"\nConnecting to {SSH_HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=15)
    print("Connected!")

    # Query PE Reviewed symbols
    print("\nFetching PE Reviewed symbols from DB...")
    reviewed_sql = """
        SELECT DISTINCT UPPER(COALESCE(s1.symbol, s2.symbol, qr.stock_symbol)) as sym
        FROM quarterly_results qr
        LEFT JOIN stocks s1 ON s1.symbol = qr.stock_symbol
        LEFT JOIN stocks s2 ON s2.bse_token = CASE
            WHEN qr.stock_symbol ~ '^[0-9]+$' THEN CAST(qr.stock_symbol AS INT)
        END
        WHERE qr.valuation IS NOT NULL AND qr.valuation != ''
          AND (qr.extraction_status = 'completed' OR qr.user_reviewed = TRUE)
    """
    reviewed_out = run_db_query(client, reviewed_sql)
    reviewed_symbols = set(line.strip().upper() for line in reviewed_out.strip().split("\n") if line.strip())
    print(f"  Found {len(reviewed_symbols)} unique symbols in PE Reviewed")

    # Query PE Pending symbols
    print("Fetching PE Pending symbols from DB...")
    pending_sql = """
        SELECT DISTINCT UPPER(COALESCE(s1.symbol, s2.symbol, qr.stock_symbol)) as sym
        FROM quarterly_results qr
        LEFT JOIN stocks s1 ON s1.symbol = qr.stock_symbol
        LEFT JOIN stocks s2 ON s2.bse_token = CASE
            WHEN qr.stock_symbol ~ '^[0-9]+$' THEN CAST(qr.stock_symbol AS INT)
        END
        WHERE (qr.valuation IS NULL OR qr.valuation = '')
    """
    pending_out = run_db_query(client, pending_sql)
    pending_symbols = set(line.strip().upper() for line in pending_out.strip().split("\n") if line.strip())
    print(f"  Found {len(pending_symbols)} unique symbols in PE Pending")

    # Also get valuation details for reviewed stocks
    print("Fetching valuation details for reviewed...")
    reviewed_detail_sql = """
        SELECT UPPER(COALESCE(s1.symbol, s2.symbol, qr.stock_symbol)) as sym,
               qr.quarter, qr.financial_year, qr.valuation
        FROM quarterly_results qr
        LEFT JOIN stocks s1 ON s1.symbol = qr.stock_symbol
        LEFT JOIN stocks s2 ON s2.bse_token = CASE
            WHEN qr.stock_symbol ~ '^[0-9]+$' THEN CAST(qr.stock_symbol AS INT)
        END
        WHERE qr.valuation IS NOT NULL AND qr.valuation != ''
          AND (qr.extraction_status = 'completed' OR qr.user_reviewed = TRUE)
        ORDER BY sym
    """
    detail_out = run_db_query(client, reviewed_detail_sql)
    reviewed_details: dict[str, list[str]] = {}
    for line in detail_out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split("|")
        if len(parts) >= 4:
            sym = parts[0].upper()
            reviewed_details.setdefault(sym, []).append(f"{parts[1]}/{parts[2]} ({parts[3]})")

    client.close()

    # Classify each Excel stock
    in_reviewed = []
    in_pending_only = []
    missing = []

    for stock in stocks:
        sym = stock["symbol"]
        if sym in reviewed_symbols:
            in_reviewed.append(stock)
        elif sym in pending_symbols:
            in_pending_only.append(stock)
        else:
            missing.append(stock)

    # Print Report
    print("\n" + "=" * 80)
    print("PE STATUS REPORT")
    print("=" * 80)

    print(f"\n{'Category':<35} {'Count':<10}")
    print("-" * 45)
    print(f"{'[DONE] PE Reviewed':<35} {len(in_reviewed):<10}")
    print(f"{'[PENDING] PE Pending':<35} {len(in_pending_only):<10}")
    print(f"{'[MISSING] Not in system':<35} {len(missing):<10}")
    print(f"{'Total in Excel':<35} {len(stocks):<10}")

    if in_pending_only:
        print(f"\n\n{'-' * 80}")
        print("STOCKS IN PE PENDING (Need to be moved to PE Reviewed)")
        print(f"{'-' * 80}")
        print(f"{'#':<5} {'Symbol':<28} {'Sector':<20}")
        print("-" * 55)
        for i, s in enumerate(in_pending_only, 1):
            print(f"{i:<5} {s['symbol']:<28} {s['sector']:<20}")

    if missing:
        print(f"\n\n{'-' * 80}")
        print("STOCKS MISSING FROM SYSTEM (Not in PE Pending or PE Reviewed)")
        print(f"{'-' * 80}")
        print(f"{'#':<5} {'Symbol':<28} {'Sector':<20}")
        print("-" * 55)
        for i, s in enumerate(missing, 1):
            print(f"{i:<5} {s['symbol']:<28} {s['sector']:<20}")

    if in_reviewed:
        print(f"\n\n{'-' * 80}")
        print("STOCKS ALREADY IN PE REVIEWED (Done)")
        print(f"{'-' * 80}")
        print(f"{'#':<5} {'Symbol':<28} {'Sector':<20} {'Latest Valuation':<30}")
        print("-" * 85)
        for i, s in enumerate(in_reviewed, 1):
            details = reviewed_details.get(s["symbol"], [])
            latest = details[0] if details else ""
            print(f"{i:<5} {s['symbol']:<28} {s['sector']:<20} {latest:<30}")

    # Summary
    pct_reviewed = (len(in_reviewed) / len(stocks) * 100) if stocks else 0
    pct_pending = (len(in_pending_only) / len(stocks) * 100) if stocks else 0
    pct_missing = (len(missing) / len(stocks) * 100) if stocks else 0
    print(f"\n\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"  Reviewed:  {len(in_reviewed):>4} / {len(stocks)} ({pct_reviewed:.1f}%)")
    print(f"  Pending:   {len(in_pending_only):>4} / {len(stocks)} ({pct_pending:.1f}%)")
    print(f"  Missing:   {len(missing):>4} / {len(stocks)} ({pct_missing:.1f}%)")

    # Save Excel with status column
    output_file = save_excel_with_status(str(excel_path), stocks, reviewed_symbols, pending_symbols)
    print(f"\n  Output Excel: {output_file}")
    print()


if __name__ == "__main__":
    main()
