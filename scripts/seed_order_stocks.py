"""
One-time script: Seed order_stocks table from existing stocks table.
Imports all active NSE stocks with default gap=3%, market=nse_cm, quantity=1.

This replicates the Google Sheet place_order_v2 tab using the
stocks table as the nse_cm_neo master data.

Usage: python scripts/seed_order_stocks.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://trade_user:trade_secure_pwd_2026@localhost:5432/automation_trade"

def main():
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        # Check current state
        count = conn.execute(text("SELECT count(*) FROM order_stocks")).scalar()
        print(f"Current order_stocks rows: {count}")

        if count > 0:
            print("Table already has data. Skipping seed.")
            print("To re-seed, run: DELETE FROM order_stocks;")
            # Show sample
            rows = conn.execute(text("""
                SELECT os.symbol, s.nse_symbol, s.nse_token
                FROM order_stocks os
                LEFT JOIN stocks s ON s.symbol = os.symbol
                LIMIT 5
            """)).fetchall()
            print("Sample (JOIN check):")
            for r in rows:
                print(f"  {r[0]} -> STOCK_NAME={r[1]}, EXCHANGE_TOKEN={r[2]}")
            return

        # Insert all active NSE stocks with nse_token into order_stocks
        result = conn.execute(text("""
            INSERT INTO order_stocks (symbol, gap, market, quantity)
            SELECT symbol, 3, 'nse_cm', 1
            FROM stocks
            WHERE is_active = true
              AND nse_token IS NOT NULL
              AND nse_symbol IS NOT NULL
            ORDER BY symbol
            ON CONFLICT (symbol) DO NOTHING
        """))
        conn.commit()

        new_count = conn.execute(text("SELECT count(*) FROM order_stocks")).scalar()
        print(f"Inserted {new_count} stocks into order_stocks")

        # Verify JOIN works (nse_cm_neo formula replication)
        rows = conn.execute(text("""
            SELECT
                os.symbol AS "OK",
                COALESCE(s.nse_symbol || '-' || s.nse_series, os.symbol) AS "STOCK_NAME",
                COALESCE(s.nse_token, 0) AS "EXCHANGE_TOKEN",
                os.gap AS "GAP",
                os.market AS "MARKET"
            FROM order_stocks os
            LEFT JOIN stocks s ON s.symbol = os.symbol
            WHERE os.symbol IN ('ACC', 'MARUTI', 'INFY', 'TCS', 'SBIN')
            ORDER BY os.symbol
        """)).fetchall()

        print("\nJOIN verification (nse_cm_neo formula check):")
        print(f"{'OK':<12} {'STOCK_NAME':<18} {'EXCHANGE_TOKEN':<16} {'GAP':<6} {'MARKET'}")
        print("-" * 65)
        for r in rows:
            print(f"{r[0]:<12} {r[1]:<18} {r[2]:<16} {r[3]:<6} {r[4]}")


if __name__ == "__main__":
    main()
