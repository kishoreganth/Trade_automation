"""
Execute database changes: merges, updates, inserts.
All operations run inside a single transaction with rollback on error.
"""

import psycopg2
from .merger import DiffResult, MergeAction, UpdateAction, InsertAction


def _escape(val) -> str:
    if val is None:
        return "NULL"
    s = str(val).replace("'", "''")
    return f"'{s}'"


def _build_merge_sql(merges: list[MergeAction]) -> list[str]:
    """Generate SQL to merge duplicate NSE+BSE rows.

    Handles the case where both NSE and BSE symbols have quarterly_results
    for the same (quarter, financial_year, announcement_date) by deleting
    the BSE duplicate before renaming.
    """
    stmts: list[str] = []

    for m in merges:
        keep = _escape(m.keep_symbol)
        delete = _escape(m.delete_symbol)

        # Delete conflicting quarterly_results that would violate the unique constraint
        stmts.append(
            f"DELETE FROM quarterly_results WHERE stock_symbol = {delete} "
            f"AND (quarter, financial_year, announcement_date) IN ("
            f"  SELECT quarter, financial_year, announcement_date "
            f"  FROM quarterly_results WHERE stock_symbol = {keep}"
            f");"
        )

        # Now safely rename remaining refs
        ref_tables = [
            ("quarterly_results", "stock_symbol"),
            ("announcement_insights", "stock_symbol"),
            ("concall_insights", "stock_symbol"),
            ("failed_extractions", "stock_symbol"),
        ]
        for table, col in ref_tables:
            stmts.append(
                f"UPDATE {table} SET {col} = {keep} "
                f"WHERE {col} = {delete};"
            )

        # Update stock_id FK in quarterly_results
        stmts.append(
            f"UPDATE quarterly_results SET stock_id = {m.keep_id} "
            f"WHERE stock_id = {m.delete_id};"
        )
        stmts.append(f"DELETE FROM stocks WHERE id = {m.delete_id};")

    return stmts


def _build_update_sql(updates: list[UpdateAction]) -> list[str]:
    """Generate SQL to update existing stock rows."""
    stmts: list[str] = []
    for u in updates:
        parts: list[str] = []
        for col, val in u.changes.items():
            if val is None:
                parts.append(f"{col} = NULL")
            elif isinstance(val, int):
                parts.append(f"{col} = {val}")
            else:
                parts.append(f"{col} = {_escape(val)}")
        parts.append("updated_at = NOW()")
        set_clause = ", ".join(parts)
        stmts.append(f"UPDATE stocks SET {set_clause} WHERE id = {u.db_id};")
    return stmts


def _build_insert_sql(inserts: list[InsertAction]) -> list[str]:
    """Generate SQL to insert new stocks."""
    stmts: list[str] = []
    for ins in inserts:
        s = ins.stock
        symbol = s.nse_symbol if s.nse_symbol else s.bse_scrip_code
        if not symbol:
            continue

        cols = [
            "symbol", "company_name", "exchange", "sector", "sub_sector",
            "isin", "nse_token", "bse_token", "nse_symbol", "bse_scrip_code",
            "nse_series", "bse_series", "market_segment", "industry_group",
            "is_active", "added_at", "updated_at",
        ]
        vals = [
            _escape(symbol),
            _escape(s.company_name) if s.company_name else "NULL",
            _escape(s.exchange),
            _escape(s.sector) if s.sector else "NULL",
            _escape(s.sub_sector) if s.sub_sector else "NULL",
            _escape(s.isin),
            str(s.nse_token) if s.nse_token else "NULL",
            str(s.bse_token) if s.bse_token else "NULL",
            _escape(s.nse_symbol) if s.nse_symbol else "NULL",
            _escape(s.bse_scrip_code) if s.bse_scrip_code else "NULL",
            _escape(s.nse_series) if s.nse_series else "NULL",
            _escape(s.bse_series) if s.bse_series else "NULL",
            _escape(s.market_segment) if s.market_segment else "NULL",
            _escape(s.industry_group) if s.industry_group else "NULL",
            "true",
            "NOW()",
            "NOW()",
        ]
        stmts.append(
            f"INSERT INTO stocks ({', '.join(cols)}) "
            f"VALUES ({', '.join(vals)}) "
            f"ON CONFLICT (symbol) DO NOTHING;"
        )
    return stmts


def generate_all_sql(diff: DiffResult) -> str:
    """Generate a complete SQL script for all changes."""
    lines: list[str] = ["BEGIN;", ""]

    merge_sql = _build_merge_sql(diff.merges)
    if merge_sql:
        lines.append(f"-- Phase A: Merge {len(diff.merges)} duplicate NSE+BSE rows")
        lines.extend(merge_sql)
        lines.append("")

    update_sql = _build_update_sql(diff.updates)
    if update_sql:
        lines.append(f"-- Phase B: Update {len(diff.updates)} existing rows")
        lines.extend(update_sql)
        lines.append("")

    insert_sql = _build_insert_sql(diff.inserts)
    if insert_sql:
        lines.append(f"-- Phase C: Insert {len(diff.inserts)} new stocks")
        lines.extend(insert_sql)
        lines.append("")

    lines.append("COMMIT;")
    return "\n".join(lines)


def apply_to_db(diff: DiffResult, dsn: str) -> dict:
    """
    Apply all changes inside a single transaction.
    Returns a summary dict with counts.
    """
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    summary = {"merges": 0, "updates": 0, "inserts": 0, "errors": []}

    try:
        # Phase A: Merges
        for stmt in _build_merge_sql(diff.merges):
            cur.execute(stmt)
        summary["merges"] = len(diff.merges)

        # Phase B: Updates
        for stmt in _build_update_sql(diff.updates):
            cur.execute(stmt)
        summary["updates"] = len(diff.updates)

        # Phase C: Inserts
        insert_stmts = _build_insert_sql(diff.inserts)
        for stmt in insert_stmts:
            try:
                cur.execute(stmt)
            except Exception as e:
                summary["errors"].append(str(e)[:200])
        summary["inserts"] = len(insert_stmts) - len(summary["errors"])

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Transaction rolled back: {e}") from e
    finally:
        cur.close()
        conn.close()

    return summary


def fetch_db_stocks(dsn: str) -> list[dict]:
    """Fetch all stocks from the database as a list of dicts."""
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, symbol, company_name, exchange, sector, sub_sector, "
        "isin, nse_token, bse_token, "
        "COALESCE(nse_symbol, '') as nse_symbol, "
        "COALESCE(bse_scrip_code, '') as bse_scrip_code, "
        "COALESCE(nse_series, '') as nse_series, "
        "COALESCE(bse_series, '') as bse_series, "
        "COALESCE(market_segment, '') as market_segment, "
        "COALESCE(industry_group, '') as industry_group, "
        "is_active "
        "FROM stocks ORDER BY id"
    )
    cols = [desc[0] for desc in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows
