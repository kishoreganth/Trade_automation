"""
One-time migration: Import place_order_v2 Google Sheet stocks into order_stocks table.
Fetches the CSV, clears existing data, and inserts only the curated stock list
with their specific GAP/MARKET/QUANTITY values.

Usage: python scripts/import_gsheet_to_order_stocks.py
"""
import io
import requests
import pandas as pd
from sqlalchemy import create_engine, text

SHEET_ID = "1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM"
GID = "1933500776"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

DB_URL = "postgresql+psycopg2://trade_user:trade_secure_pwd_2026@localhost:5432/automation_trade"


def main():
    print(f"Fetching place_order_v2 from Google Sheet...")
    resp = requests.get(SHEET_URL, timeout=30)
    if resp.status_code != 200:
        print(f"Failed to fetch sheet: HTTP {resp.status_code}")
        return

    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = df.columns.str.strip()
    print(f"Fetched {len(df)} rows, columns: {list(df.columns)}")

    if "OK" not in df.columns:
        print("ERROR: Missing 'OK' column in sheet")
        return

    # Clean GAP column (remove % if present)
    if "GAP" in df.columns:
        df["GAP"] = df["GAP"].astype(str).str.replace("%", "").str.strip()
        df["GAP"] = pd.to_numeric(df["GAP"], errors="coerce").fillna(3)

    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        # Clear existing data
        old_count = conn.execute(text("SELECT count(*) FROM order_stocks")).scalar()
        print(f"Clearing {old_count} existing rows from order_stocks...")
        conn.execute(text("DELETE FROM order_stocks"))

        # Insert from sheet (including stock_name + exchange_token)
        inserted = 0
        skipped = 0
        for _, row in df.iterrows():
            symbol = str(row.get("OK", "")).strip()
            if not symbol:
                skipped += 1
                continue

            gap = float(row.get("GAP", 3))
            market = str(row.get("MARKET", "nse_cm")).strip()
            quantity = int(float(row.get("QUANTITY", 1))) if pd.notna(row.get("QUANTITY")) else 1
            stock_name = str(row.get("STOCK_NAME", "")).strip() or None
            exchange_token = None
            if pd.notna(row.get("EXCHANGE_TOKEN")):
                try:
                    exchange_token = int(float(row["EXCHANGE_TOKEN"]))
                    if exchange_token == 0:
                        exchange_token = None
                except (ValueError, TypeError):
                    pass

            try:
                conn.execute(text("""
                    INSERT INTO order_stocks (symbol, gap, market, quantity, stock_name, exchange_token)
                    VALUES (:sym, :gap, :mkt, :qty, :sn, :et)
                    ON CONFLICT (symbol) DO UPDATE SET
                        gap = EXCLUDED.gap,
                        market = EXCLUDED.market,
                        quantity = EXCLUDED.quantity,
                        stock_name = COALESCE(EXCLUDED.stock_name, order_stocks.stock_name),
                        exchange_token = COALESCE(EXCLUDED.exchange_token, order_stocks.exchange_token),
                        is_active = true,
                        updated_at = now()
                """), {"sym": symbol, "gap": gap, "mkt": market, "qty": quantity, "sn": stock_name, "et": exchange_token})
                inserted += 1
            except Exception as e:
                print(f"  Error inserting {symbol}: {e}")
                skipped += 1

        conn.commit()

        final_count = conn.execute(text("SELECT count(*) FROM order_stocks")).scalar()
        print(f"\nDone: Imported {inserted} stocks, skipped {skipped}")
        print(f"order_stocks now has {final_count} rows")

        # Verify stored data
        rows = conn.execute(text("""
            SELECT symbol, stock_name, exchange_token, gap, market, quantity
            FROM order_stocks
            ORDER BY id
            LIMIT 10
        """)).fetchall()

        print(f"\nFirst 10 stocks (stored directly):")
        print(f"{'SYMBOL':<14} {'STOCK_NAME':<18} {'TOKEN':<8} {'GAP':<6} {'MARKET':<8} {'QTY'}")
        print("-" * 70)
        for r in rows:
            print(f"{r[0]:<14} {str(r[1] or '-'):<18} {str(r[2] or '-'):<8} {r[3]:<6} {r[4]:<8} {r[5]}")

        # Count missing tokens
        missing = conn.execute(text(
            "SELECT count(*) FROM order_stocks WHERE exchange_token IS NULL AND is_active = true"
        )).scalar()
        print(f"\nStocks with missing exchange_token: {missing}")
        print("Run 'Sync Master Scrip' after TOTP auth to fill these from Kotak API.")


if __name__ == "__main__":
    main()
