"""
Migrate data from SQLite (messages.db + analytics.db) to PostgreSQL.

Usage:
    1. Start PostgreSQL: docker compose up -d postgres
    2. Run init schema: psql or let docker-entrypoint handle init_postgres.sql
    3. Run this script: python scripts/migrate_sqlite_to_postgres.py

Environment:
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    (or defaults from backend/app/config.py)
"""

import asyncio
import sys
import os
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import aiosqlite
import asyncpg


SQLITE_MESSAGES_DB = os.getenv("SQLITE_MESSAGES_DB", "messages.db")
SQLITE_ANALYTICS_DB = os.getenv("SQLITE_ANALYTICS_DB", "analytics.db")

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "automation_trade")
PG_USER = os.getenv("POSTGRES_USER", "trade_user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "trade_secure_pwd_2026")


async def get_pg_conn():
    return await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DB,
        user=PG_USER, password=PG_PASSWORD,
    )


DATETIME_FORMATS = [
    "%d-%b-%Y %H:%M:%S",   # 02-May-2026 17:55:48
    "%d-%b-%Y",             # 02-May-2026
    "%Y-%m-%d %H:%M:%S",   # 2026-05-02 17:55:48
    "%Y-%m-%d",             # 2026-05-02
]


def parse_datetime_str(val: str) -> datetime:
    """Try fromisoformat first, then fallback to common formats."""
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        pass
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(val, fmt)
        except (ValueError, TypeError):
            continue
    raise ValueError(f"Cannot parse datetime: {val!r}")


def _parse_numeric_str(val: str):
    """Parse a numeric value that may be stored as string, including accounting
    notation '(0.13)' meaning -0.13. Returns None if unparseable."""
    s = val.strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    s = s.replace(",", "")
    try:
        n = float(s)
        return -n if neg else n
    except ValueError:
        return None


def coerce_value(val, pg_type: str):
    """Convert SQLite values to proper Python types for asyncpg."""
    if val is None:
        return None
    if pg_type in ("timestamptz", "timestamp with time zone", "timestamp without time zone"):
        if isinstance(val, str):
            return parse_datetime_str(val)
        return val
    if pg_type == "date":
        if isinstance(val, str):
            try:
                return date.fromisoformat(val)
            except ValueError:
                return parse_datetime_str(val).date()
        return val
    if pg_type == "boolean":
        if isinstance(val, int):
            return bool(val)
        return val
    if pg_type in ("double precision", "real", "numeric") and isinstance(val, str):
        parsed = _parse_numeric_str(val)
        return parsed
    return val


async def get_pg_column_types(pg, pg_table: str) -> dict:
    """Fetch {column_name: data_type} from information_schema."""
    rows = await pg.fetch(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = $1",
        pg_table,
    )
    return {r["column_name"]: r["data_type"] for r in rows}


async def migrate_table(sqlite_db_path: str, table: str, pg_table: str, column_map: dict,
                        fk_nullify: dict | None = None):
    """
    Generic migration: read all rows from SQLite table, batch-insert into PostgreSQL.
    column_map: {sqlite_col: pg_col} — maps source to destination column names.
    fk_nullify: {col_name: (ref_table, ref_col)} — nullify col if value doesn't exist in ref table.
    """
    if not Path(sqlite_db_path).exists():
        print(f"  SKIP: {sqlite_db_path} not found")
        return 0

    pg = await get_pg_conn()
    try:
        col_types = await get_pg_column_types(pg, pg_table)

        # Pre-load valid FK values for nullification
        valid_fk_values: dict[str, set] = {}
        if fk_nullify:
            for col, (ref_table, ref_col) in fk_nullify.items():
                rows_fk = await pg.fetch(f"SELECT {ref_col} FROM {ref_table}")
                valid_fk_values[col] = {r[ref_col] for r in rows_fk}

        async with aiosqlite.connect(sqlite_db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                cursor = await db.execute(f"SELECT * FROM {table}")
                rows = await cursor.fetchall()
            except Exception as e:
                msg = str(e).lower()
                if "no such table" in msg:
                    print(f"  SKIP: table '{table}' not found in {sqlite_db_path}")
                    return 0
                raise

        if not rows:
            print(f"  {table}: 0 rows (empty)")
            return 0

        sqlite_cols = list(column_map.keys())
        pg_cols = list(column_map.values())
        placeholders = ", ".join(f"${i+1}" for i in range(len(pg_cols)))
        cols_str = ", ".join(pg_cols)

        insert_sql = f"""
            INSERT INTO {pg_table} ({cols_str})
            VALUES ({placeholders})
            ON CONFLICT DO NOTHING
        """

        batch = []
        nullified_count = 0
        for row in rows:
            values = []
            for sc, pc in zip(sqlite_cols, pg_cols):
                val = row[sc] if sc in row.keys() else None
                # Nullify invalid FK references
                if pc in valid_fk_values and val is not None:
                    if val not in valid_fk_values[pc]:
                        val = None
                        nullified_count += 1
                val = coerce_value(val, col_types.get(pc, ""))
                values.append(val)
            batch.append(tuple(values))

        if nullified_count:
            print(f"    INFO: nullified {nullified_count} invalid FK references")

        count = 0
        chunk_size = 500
        for i in range(0, len(batch), chunk_size):
            chunk = batch[i:i + chunk_size]
            for record in chunk:
                try:
                    await pg.execute(insert_sql, *record)
                    count += 1
                except Exception as e:
                    err_msg = str(e).split("\n")[0]
                    print(f"    WARN: skip row in {table}: {err_msg}")
                    continue

        print(f"  {table} -> {pg_table}: {count}/{len(rows)} rows migrated")
        return count
    finally:
        await pg.close()


async def migrate_messages_db():
    print("\n=== Migrating messages.db ===")

    await migrate_table(SQLITE_MESSAGES_DB, "messages", "messages", {
        "id": "id",
        "chat_id": "chat_id",
        "message": "message",
        "timestamp": "timestamp",
        "symbol": "symbol",
        "company_name": "company_name",
        "description": "description",
        "file_url": "file_url",
        "raw_message": "raw_message",
        "option": "option",
        "sector": "sector",
        "exchange": "exchange",
    })

    await migrate_table(SQLITE_MESSAGES_DB, "users", "users", {
        "id": "id",
        "username": "username",
        "password_hash": "password_hash",
        "created_at": "created_at",
        "last_login": "last_login",
    })

    await migrate_table(SQLITE_MESSAGES_DB, "sessions", "sessions", {
        "id": "id",
        "session_token": "session_token",
        "user_id": "user_id",
        "created_at": "created_at",
        "expires_at": "expires_at",
    })

    await migrate_table(SQLITE_MESSAGES_DB, "scheduled_fetch_config", "scheduled_fetch_config", {
        "id": "id",
        "enabled": "enabled",
        "hour": "hour",
        "minute": "minute",
        "second": "second",
        "weekdays_only": "weekdays_only",
        "updated_at": "updated_at",
    })


async def migrate_analytics_db():
    print("\n=== Migrating analytics.db ===")

    await migrate_table(SQLITE_ANALYTICS_DB, "stocks", "stocks", {
        "id": "id",
        "symbol": "symbol",
        "company_name": "company_name",
        "exchange": "exchange",
        "sector": "sector",
        "sub_sector": "sub_sector",
        "is_active": "is_active",
        "added_at": "added_at",
        "updated_at": "updated_at",
        "nse_token": "nse_token",
        "bse_token": "bse_token",
        "isin": "isin",
    })

    await migrate_table(SQLITE_ANALYTICS_DB, "quarterly_results", "quarterly_results", {
        "id": "id",
        "stock_symbol": "stock_symbol",
        "company_name": "company_name",
        "quarter": "quarter",
        "financial_year": "financial_year",
        "period_ended": "period_ended",
        "eps_basic_standalone": "eps_basic_standalone",
        "eps_diluted_standalone": "eps_diluted_standalone",
        "eps_basic_consolidated": "eps_basic_consolidated",
        "eps_diluted_consolidated": "eps_diluted_consolidated",
        "fy_eps_basic_standalone": "fy_eps_basic_standalone",
        "fy_eps_diluted_standalone": "fy_eps_diluted_standalone",
        "fy_eps_basic_consolidated": "fy_eps_basic_consolidated",
        "fy_eps_diluted_consolidated": "fy_eps_diluted_consolidated",
        "fy_eps_formula_standalone": "fy_eps_formula_standalone",
        "fy_eps_formula_consolidated": "fy_eps_formula_consolidated",
        "standalone_data": "standalone_data",
        "consolidated_data": "consolidated_data",
        "raw_ai_response": "raw_ai_response",
        "source_pdf_url": "source_pdf_url",
        "source_message_id": "source_message_id",
        "exchange": "exchange",
        "units": "units",
        "created_at": "created_at",
        "updated_at": "updated_at",
        "announcement_date": "announcement_date",
        "stock_id": "stock_id",
        "cmp": "cmp",
        "pe": "pe",
        "cmp_updated_at": "cmp_updated_at",
        "cumulative_eps_basic_standalone": "cumulative_eps_basic_standalone",
        "cumulative_eps_diluted_standalone": "cumulative_eps_diluted_standalone",
        "cumulative_eps_basic_consolidated": "cumulative_eps_basic_consolidated",
        "cumulative_eps_diluted_consolidated": "cumulative_eps_diluted_consolidated",
        "valuation": "valuation",
        "comments": "comments",
        "extraction_status": "extraction_status",
        "extraction_error": "extraction_error",
        "source_pdf_url_tracking": "source_pdf_url_tracking",
        "recommendation": "recommendation",
        "target_price": "target_price",
        "manual_fy_eps": "manual_fy_eps",
        "manual_fy_eps_formula": "manual_fy_eps_formula",
    }, fk_nullify={"stock_id": ("stocks", "id")})

    await migrate_table(SQLITE_ANALYTICS_DB, "failed_extractions", "failed_extractions", {
        "id": "id",
        "stock_symbol": "stock_symbol",
        "pdf_url": "pdf_url",
        "exchange": "exchange",
        "announcement_date": "announcement_date",
        "error_message": "error_message",
        "attempts": "attempts",
        "status": "status",
        "created_at": "created_at",
        "resolved_at": "resolved_at",
    })

    await migrate_table(SQLITE_ANALYTICS_DB, "pe_formulas", "pe_formulas", {
        "id": "id",
        "name": "name",
        "q1_expr": "q1_expr",
        "q2_expr": "q2_expr",
        "q3_expr": "q3_expr",
        "q4_expr": "q4_expr",
        "is_default": "is_default",
        "created_at": "created_at",
        "updated_at": "updated_at",
    })

    await migrate_table(SQLITE_ANALYTICS_DB, "sector_formulas", "sector_formulas", {
        "id": "id",
        "sector": "sector",
        "sub_sector": "sub_sector",
        "quarter": "quarter",
        "formula_expr": "formula_expr",
        "created_at": "created_at",
        "updated_at": "updated_at",
    })

    await migrate_table(SQLITE_ANALYTICS_DB, "bse_announcements_log", "bse_announcements_log", {
        "id": "id",
        "scrip_code": "scrip_code",
        "company_name": "company_name",
        "announcement_type": "announcement_type",
        "announcement_date": "announcement_date",
        "subject": "subject",
        "pdf_url": "pdf_url",
        "xml_url": "xml_url",
        "exchange": "exchange",
        "processed": "processed",
        "created_at": "created_at",
        "processed_at": "processed_at",
    })


async def normalize_financial_years():
    """Normalize financial_year values like 'FY2025-26' to '2026'."""
    print("\n=== Normalizing financial_year formats ===")
    pg = await get_pg_conn()
    try:
        rows = await pg.fetch(
            "SELECT DISTINCT financial_year FROM quarterly_results WHERE financial_year LIKE 'FY%'"
        )
        for row in rows:
            fy_raw = row["financial_year"]
            # Extract ending year: 'FY2025-26' -> '2026', 'FY24' -> '2024'
            if "-" in fy_raw:
                suffix = fy_raw.split("-")[-1]
                century = "20" if len(suffix) == 2 else ""
                normalized = century + suffix
            else:
                digits = fy_raw.replace("FY", "")
                normalized = ("20" + digits) if len(digits) == 2 else digits
            updated = await pg.execute(
                "UPDATE quarterly_results SET financial_year = $1 WHERE financial_year = $2",
                normalized, fy_raw,
            )
            print(f"  '{fy_raw}' -> '{normalized}': {updated.split()[-1]} rows")
    finally:
        await pg.close()


async def reset_sequences():
    """Reset PostgreSQL auto-increment sequences to max(id) + 1 after data import."""
    print("\n=== Resetting sequences ===")
    pg = await get_pg_conn()
    try:
        tables = ["messages", "users", "sessions", "scheduled_fetch_config",
                  "stocks", "quarterly_results", "failed_extractions",
                  "pe_formulas", "sector_formulas", "bse_announcements_log"]
        for table in tables:
            try:
                max_id = await pg.fetchval(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
                if max_id > 0:
                    await pg.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {max_id})"
                    )
                    print(f"  {table}: sequence set to {max_id}")
            except Exception as e:
                print(f"  {table}: sequence reset failed: {e}")
    finally:
        await pg.close()


async def verify_migration():
    """Print row counts from PostgreSQL for verification."""
    print("\n=== Verification (PostgreSQL row counts) ===")
    pg = await get_pg_conn()
    try:
        tables = ["messages", "users", "sessions", "stocks",
                  "quarterly_results", "failed_extractions",
                  "pe_formulas", "sector_formulas", "bse_announcements_log"]
        for table in tables:
            count = await pg.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"  {table}: {count} rows")
    finally:
        await pg.close()


async def truncate_all():
    """Truncate all tables before re-migration to avoid duplicates."""
    print("\n=== Truncating all tables ===")
    pg = await get_pg_conn()
    try:
        tables = [
            "bse_announcements_log", "sector_formulas", "pe_formulas",
            "failed_extractions", "quarterly_results", "stocks",
            "scheduled_fetch_config", "sessions", "users", "messages",
        ]
        for table in tables:
            await pg.execute(f"TRUNCATE TABLE {table} CASCADE")
            print(f"  {table}: truncated")
    finally:
        await pg.close()


async def main():
    clean = "--clean" in sys.argv

    print("=" * 60)
    print("SQLite -> PostgreSQL Migration")
    print("=" * 60)
    print(f"Source: {SQLITE_MESSAGES_DB}, {SQLITE_ANALYTICS_DB}")
    print(f"Target: postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DB}")
    print("=" * 60)

    if clean:
        await truncate_all()

    await migrate_messages_db()
    await migrate_analytics_db()
    await normalize_financial_years()
    await reset_sequences()
    await verify_migration()

    print("\n[OK] Migration complete!")


if __name__ == "__main__":
    asyncio.run(main())
