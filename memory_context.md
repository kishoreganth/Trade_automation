# Memory Context — Automation_TRADE

## Project Overview
Stock trading automation system with Next.js frontend + FastAPI backend + PostgreSQL + Redis + Celery.
Kotak Neo broker API integration for order placement. NSE/BSE announcement processing with AI insights.

## Architecture
- **Frontend**: Next.js 14 (App Router), Tailwind CSS, `frontend/src/`
- **Backend**: FastAPI, async SQLAlchemy, `backend/app/`
- **DB**: PostgreSQL (asyncpg), Alembic migrations (latest: 013)
- **Queue**: Celery + Redis for background tasks
- **Broker**: Kotak Neo API (session-based auth with TOTP)

## Key Tables
- `stocks` — master stock list (symbol, nse_token, nse_symbol, bse_token, sector, etc.)
- `order_stocks` — place-order stock config (symbol, gap, market, quantity, open_price, buy/sell_order, stock_name, exchange_token) [012+013]
- `messages` — telegram/NSE announcements
- `quarterly_results` — PE analysis data
- `scheduled_fetch_config` — cron config

## Recent Changes

### 2026-06-04: Postgres Order Stock Toggle (ENV-based GSheet/Postgres Switch)
**Problem**: Gmail storage full → Google Sheet CSV export fails → Get Quotes broken.

**Solution**: ENV toggle `ORDER_DATA_SOURCE=gsheet|postgres` to switch between Google Sheet and PostgreSQL for the Place Order page.

**Files created**:
- `backend/alembic/versions/012_order_stocks.py` — migration for `order_stocks` table
- `backend/app/services/order_stock_db.py` — DB service (get_order_stocks_df, save_order_stock_prices, bulk_import_stocks)

**Files modified**:
- `backend/app/routers/orders.py` — ENV toggle in /sheet, /quotes/fetch, /execute/all + new endpoints: /source, /stocks/import, /stocks/upload, /stocks/{symbol} DELETE
- `frontend/src/lib/api.ts` — added getOrderSource(), uploadOrderStocksFile(), importOrderStocks(), deleteOrderStock()
- `frontend/src/app/place-order/page.tsx` — source badge (Postgres/GSheet), Import Stocks button (CSV/Excel upload), source-aware steps
- `.env.example` — added ORDER_DATA_SOURCE=gsheet

**How nse_cm_neo formula is replicated**:
- Google Sheet formula: `STOCK_NAME = INDEX(nse_cm_neo!A:A, MATCH(OK, nse_cm_neo!E:E, 0))`
- Postgres equivalent: `SELECT s.nse_symbol || '-' || s.nse_series AS "STOCK_NAME", s.nse_token AS "EXCHANGE_TOKEN" FROM order_stocks os LEFT JOIN stocks s ON s.symbol = os.symbol`
- STOCK_NAME format: `{nse_symbol}-{nse_series}` e.g. "ACC-EQ", "MARUTI-EQ" (matches Kotak API `ts` field format)
- BUY/SELL ORDER calculation stays in get_quote.py (unchanged): `BUY = OPEN_PRICE * (1 - GAP/100)`, `SELL = OPEN_PRICE * (1 + GAP/100)`

**Seeding**: NEVER use `seed_order_stocks.py` (it wrongly imports ALL 3658 stocks from `stocks` table). ALWAYS use `import_gsheet_to_order_stocks.py` which imports ONLY the curated ~1850 stocks from the Google Sheet. The `order_stocks` table must NEVER contain more stocks than the Google Sheet. The `stocks` table is a separate master reference — NOT a source for order_stocks.

**.env loading**: `orders.py` loads both `Automation_TRADE/.env` and `backend/.env` (backend takes precedence).

**Existing files NOT touched**: gsheet_stock_get.py, get_quote.py, place_order.py, quote_fetcher.py

**Toggle**: Set `ORDER_DATA_SOURCE=postgres` in backend/.env to use Postgres, or `ORDER_DATA_SOURCE=gsheet` (default) to use Google Sheet.

**Performance**: Postgres mode eliminates Google Sheet CSV export latency (~2-5s per request) and Gmail storage dependency.

### 2026-06-04: Master Scrip Sync (Kotak API → order_stocks tokens)
**Problem**: ~91 stocks had missing EXCHANGE_TOKEN because `stocks` table (from TrueData CSVs) didn't cover all Kotak symbols. Stock symbol/token changes over time weren't handled.

**Solution**: Direct Kotak master scrip sync — fetches `nse_cm-v1.csv` + `bse_cm-v1.csv` from Kotak API and updates `stock_name` + `exchange_token` columns directly in `order_stocks`.

**Files created**:
- `backend/alembic/versions/013_order_stocks_direct_cols.py` — adds `stock_name` (VARCHAR) + `exchange_token` (INT) columns to `order_stocks`
- `backend/app/services/master_scrip_sync.py` — fetches Kotak session → downloads CSV URLs → parses NSE EQ + BSE A/B → updates order_stocks

**Files modified**:
- `backend/app/services/order_stock_db.py` — query uses `COALESCE(os.stock_name, s.nse_symbol||'-'||s.nse_series, os.symbol)` for STOCK_NAME, `COALESCE(os.exchange_token, s.nse_token, 0)` for EXCHANGE_TOKEN. `bulk_import_stocks` now accepts stock_name + exchange_token.
- `backend/app/routers/orders.py` — added `POST /api/place_order/sync_master_scrip` endpoint
- `frontend/src/lib/api.ts` — added `syncMasterScrip()` function (120s timeout)
- `frontend/src/app/place-order/page.tsx` — "Sync Tokens" button (amber) next to Import Stocks
- `scripts/import_gsheet_to_order_stocks.py` — now imports STOCK_NAME + EXCHANGE_TOKEN from GSheet

**Sync flow**: TOTP auth → Kotak session → GET /masterscrip/file-paths → download nse_cm-v1.csv (filter EQ) → download bse_cm-v1.csv (filter A/B) → UPDATE order_stocks SET stock_name, exchange_token for matching symbols. NSE EQ priority, BSE A/B fallback for missing.

**Performance**: 1759/1850 stocks now have direct tokens from GSheet import. Remaining ~91 filled after first "Sync Tokens" click post-auth. Eliminates dependency on `stocks` table JOIN for token resolution.
