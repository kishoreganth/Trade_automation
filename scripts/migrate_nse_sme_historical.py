"""
Migrate NSE SME Historical Financial Results into DB
=====================================================
Reads the pre-fetched JSON (from test_nse_sme_historical.py) and inserts:
  1. bse_announcements_log (dedup record)
  2. quarterly_results (PE Pending entry, extraction_status='completed')

NO AI extraction is triggered. Rows appear on PE Pending (no valuation yet).

Usage:
  python scripts/migrate_nse_sme_historical.py --local --dry-run
  python scripts/migrate_nse_sme_historical.py --local
  python scripts/migrate_nse_sme_historical.py --remote
"""

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = SCRIPT_DIR / "nse_sme_historical"
ENV_FILE = PROJECT_ROOT / "backend" / ".env"

SSH_HOST = "122.165.113.41"
SSH_USER = "kishore"
SSH_PASS = "root"
DB_CONTAINER = "trade_postgres"

IST = timezone(timedelta(hours=5, minutes=30))

DRY_RUN = "--dry-run" in sys.argv
USE_LOCAL = "--local" in sys.argv
USE_REMOTE = "--remote" in sys.argv

if not USE_LOCAL and not USE_REMOTE:
    USE_LOCAL = True  # default: local first


def load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def find_latest_json() -> Path:
    files = sorted(DATA_DIR.glob("nse_sme_financial_results_*.json"), reverse=True)
    if not files:
        print("ERROR: No financial results JSON found in scripts/nse_sme_historical/")
        print("Run test_nse_sme_historical.py first.")
        sys.exit(1)
    return files[0]


def parse_nse_datetime(dt_str: str) -> datetime:
    formats = [
        "%d-%b-%Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",
        "%d-%b-%Y",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(dt_str.strip(), fmt)
            return parsed.replace(tzinfo=IST)
        except (ValueError, AttributeError):
            continue
    return datetime.now(IST)


def quarter_fy_from_date(ann_date: datetime) -> tuple[str, str]:
    y, m = ann_date.year, ann_date.month
    if 4 <= m <= 6:
        return "Q4", f"{y - 1}-{str(y)[-2:]}"
    elif 7 <= m <= 9:
        return "Q1", f"{y}-{str(y + 1)[-2:]}"
    elif 10 <= m <= 12:
        return "Q2", f"{y}-{str(y + 1)[-2:]}"
    else:
        return "Q3", f"{y - 1}-{str(y)[-2:]}"


def parse_period_from_text(text: str) -> tuple[str, str] | None:
    text_lower = text.lower()
    m = re.search(r"period ended\s+(\w+)\s+\d{1,2},?\s+(\d{4})", text_lower)
    if not m:
        m = re.search(r"period ended\s+(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text_lower)
        if m:
            month_num = int(m.group(2))
            year = int(m.group(3))
        else:
            return None
    else:
        month_str = m.group(1)
        year = int(m.group(2))
        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
        }
        month_num = month_map.get(month_str, 0)
        if not month_num:
            return None

    if month_num == 3:
        return "Q4", f"{year - 1}-{str(year)[-2:]}"
    elif month_num == 6:
        return "Q1", f"{year}-{str(year + 1)[-2:]}"
    elif month_num == 9:
        return "Q2", f"{year}-{str(year + 1)[-2:]}"
    elif month_num == 12:
        return "Q3", f"{year}-{str(year + 1)[-2:]}"

    return None


def build_records(data: list[dict]) -> list[dict]:
    records = []
    for ann in data:
        symbol = ann.get("symbol", "").strip()
        company_name = ann.get("sm_name", "").strip()
        pdf_url = ann.get("attchmntFile", "").strip()
        an_dt_str = ann.get("an_dt") or ann.get("dt") or ""
        attchmnt_text = ann.get("attchmntText", "")
        desc = ann.get("desc", "")

        if not symbol or not pdf_url:
            continue

        ann_date = parse_nse_datetime(an_dt_str)
        period_info = parse_period_from_text(attchmnt_text)
        if period_info:
            quarter, fy = period_info
        else:
            quarter, fy = quarter_fy_from_date(ann_date)

        records.append({
            "symbol": symbol,
            "company_name": company_name,
            "pdf_url": pdf_url,
            "ann_date_str": an_dt_str,
            "ann_date": ann_date.strftime("%Y-%m-%d"),
            "quarter": quarter,
            "fy": fy,
            "desc": desc,
        })
    return records


def get_db_counts_local(conn) -> dict:
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM quarterly_results qr
        LEFT JOIN stocks s ON s.symbol = qr.stock_symbol
        WHERE qr.exchange = 'NSE'
          AND qr.announcement_date >= '2026-04-01'
          AND qr.announcement_date <= '2026-05-30'
          AND COALESCE(s.nse_series, '') IN ('SM', 'ST')
    """)
    sme_qr = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM quarterly_results
        WHERE exchange = 'NSE'
          AND announcement_date >= '2026-04-01'
          AND announcement_date <= '2026-05-30'
          AND (valuation IS NULL OR valuation = '')
    """)
    pending = cur.fetchone()[0]
    cur.close()
    return {"sme_qr": sme_qr, "pending_nse": pending}


def migrate_local(records: list[dict], env: dict) -> tuple[int, int, int, int, list[str]]:
    import psycopg2

    host = env.get("POSTGRES_HOST", "localhost")
    port = int(env.get("POSTGRES_PORT", "5432"))
    dbname = env.get("POSTGRES_DB", "automation_trade")
    user = env.get("POSTGRES_USER", "trade_user")
    password = env.get("POSTGRES_PASSWORD", "")

    print(f"\nConnecting to local Postgres: {user}@{host}:{port}/{dbname}...")
    conn = psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password,
    )
    conn.autocommit = False
    print("Connected!")

    before = get_db_counts_local(conn)
    print(f"  Before: NSE SME QR rows (Apr-May): {before['sme_qr']}, NSE pending: {before['pending_nse']}")

    inserted_log = skipped_log = inserted_qr = skipped_qr = 0
    errors: list[str] = []
    cur = conn.cursor()

    sql_log = """
        INSERT INTO bse_announcements_log
        (scrip_code, company_name, announcement_type, announcement_date, subject, pdf_url, exchange, processed, created_at)
        VALUES (%s, %s, 'quarterly_result', %s, %s, %s, 'NSE', 0, NOW())
        ON CONFLICT (scrip_code, announcement_type, pdf_url) DO NOTHING
        RETURNING id
    """
    sql_qr = """
        INSERT INTO quarterly_results
        (stock_symbol, company_name, quarter, financial_year,
         source_pdf_url, exchange, extraction_status,
         announcement_date, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'NSE', 'completed', %s, NOW(), NOW())
        ON CONFLICT (stock_symbol, quarter, financial_year, announcement_date)
        DO NOTHING
        RETURNING id
    """

    for i, rec in enumerate(records, 1):
        try:
            cur.execute(sql_log, (
                rec["symbol"], rec["company_name"], rec["ann_date_str"],
                rec["desc"], rec["pdf_url"],
            ))
            if cur.fetchone():
                inserted_log += 1
            else:
                skipped_log += 1

            cur.execute(sql_qr, (
                rec["symbol"], rec["company_name"], rec["quarter"], rec["fy"],
                rec["pdf_url"], rec["ann_date"],
            ))
            if cur.fetchone():
                inserted_qr += 1
            else:
                skipped_qr += 1

            if i % 50 == 0:
                conn.commit()
                print(f"  [{i}/{len(records)}] Log: +{inserted_log} skip:{skipped_log} | QR: +{inserted_qr} skip:{skipped_qr}")

        except Exception as e:
            conn.rollback()
            errors.append(f"{rec['symbol']}: {e}")

    conn.commit()
    after = get_db_counts_local(conn)
    print(f"  After:  NSE SME QR rows (Apr-May): {after['sme_qr']}, NSE pending: {after['pending_nse']}")

    cur.close()
    conn.close()
    return inserted_log, skipped_log, inserted_qr, skipped_qr, errors


def migrate_remote(records: list[dict]) -> tuple[int, int, int, int, list[str]]:
    import paramiko

    def escape_sql_str(s: str) -> str:
        return s.replace("'", "''")

    def run_sql(client, sql: str) -> str:
        escaped_sql = sql.replace("'", "'\\''")
        cmd = f"docker exec {DB_CONTAINER} psql -U trade_user -d automation_trade -t -A -F '|' -c '{escaped_sql}'"
        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if stderr.channel.recv_exit_status() != 0 and not out:
            raise RuntimeError(f"SQL failed: {err}")
        return out

    print(f"\nConnecting to remote server {SSH_HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=15)
    print("Connected!")

    inserted_log = skipped_log = inserted_qr = skipped_qr = 0
    errors: list[str] = []

    for i, rec in enumerate(records, 1):
        sym = escape_sql_str(rec["symbol"])
        cn = escape_sql_str(rec["company_name"])
        pdf = escape_sql_str(rec["pdf_url"])
        desc = escape_sql_str(rec["desc"])
        ann_dt_str = escape_sql_str(rec["ann_date_str"])

        sql_log = f"""
            INSERT INTO bse_announcements_log
            (scrip_code, company_name, announcement_type, announcement_date, subject, pdf_url, exchange, processed, created_at)
            VALUES ('{sym}', '{cn}', 'quarterly_result', '{ann_dt_str}', '{desc}', '{pdf}', 'NSE', 0, NOW())
            ON CONFLICT (scrip_code, announcement_type, pdf_url) DO NOTHING
        """
        sql_qr = f"""
            INSERT INTO quarterly_results
            (stock_symbol, company_name, quarter, financial_year,
             source_pdf_url, exchange, extraction_status,
             announcement_date, created_at, updated_at)
            VALUES ('{sym}', '{cn}', '{rec['quarter']}', '{rec['fy']}', '{pdf}', 'NSE', 'completed',
                    '{rec['ann_date']}', NOW(), NOW())
            ON CONFLICT (stock_symbol, quarter, financial_year, announcement_date)
            DO NOTHING
        """

        try:
            run_sql(client, sql_log)
            inserted_log += 1
        except Exception as e:
            if "duplicate" in str(e).lower() or "conflict" in str(e).lower():
                skipped_log += 1
            else:
                errors.append(f"LOG {sym}: {e}")

        try:
            run_sql(client, sql_qr)
            inserted_qr += 1
        except Exception as e:
            if "duplicate" in str(e).lower() or "conflict" in str(e).lower():
                skipped_qr += 1
            else:
                errors.append(f"QR {sym}: {e}")

        if i % 50 == 0 or i == len(records):
            print(f"  [{i}/{len(records)}] Log: +{inserted_log} skip:{skipped_log} | QR: +{inserted_qr} skip:{skipped_qr}")

    client.close()
    return inserted_log, skipped_log, inserted_qr, skipped_qr, errors


def main():
    target = "LOCAL" if USE_LOCAL else "REMOTE"
    json_path = find_latest_json()

    print("=" * 80)
    print("NSE SME HISTORICAL MIGRATION")
    print(f"Source: {json_path.name}")
    print(f"Target: {target}")
    print(f"Mode: {'DRY RUN (no writes)' if DRY_RUN else 'LIVE (writing to DB)'}")
    print("=" * 80)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    records = build_records(data)
    print(f"\nTotal financial results in JSON: {len(data)}")
    print(f"Valid records to migrate: {len(records)}")

    qfy_counter: dict[str, int] = {}
    for r in records:
        key = f"{r['quarter']} {r['fy']}"
        qfy_counter[key] = qfy_counter.get(key, 0) + 1

    print("\nQuarter/FY breakdown:")
    for key in sorted(qfy_counter.keys()):
        print(f"  {key}: {qfy_counter[key]}")

    if DRY_RUN:
        print(f"\n[DRY RUN] Would insert up to {len(records)} records. Exiting.")
        if USE_LOCAL:
            print("\nNext: python scripts/migrate_nse_sme_historical.py --local")
        return

    if USE_LOCAL:
        env = load_env()
        inserted_log, skipped_log, inserted_qr, skipped_qr, errors = migrate_local(records, env)
    else:
        inserted_log, skipped_log, inserted_qr, skipped_qr, errors = migrate_remote(records)

    print(f"\n{'=' * 80}")
    print("MIGRATION COMPLETE")
    print(f"{'=' * 80}")
    print(f"\n  bse_announcements_log:")
    print(f"    Inserted: {inserted_log}")
    print(f"    Skipped (already exists): {skipped_log}")
    print(f"\n  quarterly_results:")
    print(f"    Inserted: {inserted_qr}")
    print(f"    Skipped (already exists): {skipped_qr}")

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors[:20]:
            print(f"    {e}")

    print(f"\n  Verify locally:")
    print(f"    1. Open http://localhost:3000/analytics/pe-pending")
    print(f"    2. Filter: Exchange=NSE, Segment=NSE SME")
    print(f"    3. Date range: Apr 1 - May 30, 2026")
    if USE_LOCAL:
        print(f"\n  When satisfied, run on server:")
        print(f"    python scripts/migrate_nse_sme_historical.py --remote")
    print(f"\n{'=' * 80}")


if __name__ == "__main__":
    main()
