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

### 2026-06-05: Run Status Tracking (Persistent Last-Run Info)
**Problem**: No way to see when Get Quotes or Place Orders last ran successfully after page refresh.

**Solution**: Persist last-run status for both operations in Redis. Show success/failure, timestamp, and summary stats in the UI.

**Files modified**:
- `backend/app/routers/orders.py` — added `_save_run_status()` / `_get_run_status()` helpers using Redis keys `run_status:quotes` / `run_status:orders`. Added `GET /api/place_order/run-status` endpoint. Both `_fetch_quotes_*` and `_place_all_orders_*` now save status on success/failure.
- `frontend/src/lib/api.ts` — added `getRunStatus()` function
- `frontend/src/app/place-order/page.tsx` — loads persistent status on mount via `loadRunStatus()`, refreshes after each quotes/orders action. Shows green/red status cards below Get Quotes and Place Orders buttons with timestamp + stats.

**Tested**: Session active, Get Quotes fetched 1772/1776 stocks in 4.8s, all prices saved to Postgres.

### 2026-06-05: Live Order Progress Bar (Background + Polling)
**Problem**: Place Orders runs ~3600 orders over several minutes. Frontend HTTP timeout (30s) caused disconnect — backend kept running but frontend showed stale "success" from previous run.

**Solution**: Fire-and-forget background execution + Redis polling for progress.

**Flow**: `POST /execute/all` returns immediately → `asyncio.create_task(_run_orders_background)` → progress saved to Redis every order → frontend polls `GET /order-progress` every 2s → detects `status: "completed"` or `"error"` and stops.

**Files modified**:
- `backend/app/services/place_order.py` — added optional `progress_callback` param to `place_orders_with_rate_limit()`. After each order completes, calls callback with `{total, completed, success, failed, pending, percent, current_stock, status}`.
- `backend/app/routers/orders.py` — `POST /execute/all` now starts orders via `asyncio.create_task()` and returns immediately (`{started: true}`). Progress saved to Redis key `order_progress:live` (600s TTL). `_save_order_final()` sets `status: "completed"` or `"error"`. `GET /order-progress` returns current progress. Prevents double-start via `_order_task_running` flag.
- `frontend/src/app/place-order/page.tsx` — `handlePlaceOrders` no longer awaits completion. Polls `/order-progress` every 2s. Detects `status: "completed"` → stops polling, shows toast, updates run status. Detects `status: "error"` → shows error. 3-color bar: green=success, red=failed, gray=pending with counts.
- `frontend/src/hooks/useWebSocket.tsx` — added `subscribe()`/`useWSEvent()` (kept for future use, not used by orders).

### 2026-06-09: PE Status Check — Symbol Mismatch Fix (v2)
**Problem**: `scripts/check_pe_status.py` marked 1068/1964 stocks as "NOT FOUND" because Excel uses abbreviated names (`TINNA RUBBER`, `INDAG RUBBER`, `JASCH`) while DB stores NSE tickers (`TINNARUBR`), BSE codes (`509162`), or no-space names (`NACLIND`). Direct string match failed massively.

**Solution**: 6-strategy symbol matching in `check_pe_status.py`:
1. Direct match (exact symbol)
2. No-space match (remove spaces/& from Excel symbol)
3. Stocks table bridge (nospace→symbol via stocks table, then check QR)
4. BSE code reverse lookup (quarterly_results BSE codes → stocks.bse_token → resolve)
5. First-word prefix match (`TINNA RUBBER` → first word `TINNA` → matches `TINNARUBR`)
6. Company name partial match (quarterly_results.company_name words → match Excel symbol words)

**Files modified**: `scripts/check_pe_status.py` — full rewrite. `build_db_context()` fetches stocks table + QR symbols + company names in bulk. `match_symbol()` applies all 6 strategies. `save_excel_with_status()` has PermissionError fallback. 4 status categories: REVIEWED (green), PENDING (yellow), IN_STOCKS (blue), NOT FOUND (red). Sector breakdown in console.

**Result**: NOT FOUND dropped from 1068 → **68** (3.5%). REVIEWED: 1200 (61.1%), PENDING: 512 (26.1%), IN_STOCKS: 184 (9.4%). 1000 stocks correctly reclassified.

**Performance**: Script runs in ~20s via SSH → docker exec → psql. All data fetched in bulk (no per-stock queries).

### 2026-06-10: Segment Filter for PE Pending & PE Reviewed
**Problem**: No way to filter PE analysis results by market segment (NSE_EQ, NSE_SME, BSE_EQ, BSE_SME).

**Solution**: Added segment filter dropdown to Row 1 filters (alongside Year/Quarter/Exchange) on both PE Pending and PE Reviewed pages.

**Files modified**:
- `backend/app/routers/pe_analysis.py` — added `segment` query param to `get_pe_analysis()`, filters via `outer_conditions` on computed `market_segment` column. Added `segments` list to `get_pe_filters()` response. Updated cache key.
- `frontend/src/lib/api.ts` — added `segment` to `fetchPEAnalysis` params type
- `frontend/src/hooks/usePEAnalysis.ts` — added `segment` to `PEFilters` interface
- `frontend/src/app/analytics/pe-pending/page.tsx` — added Segment FilterBadge in Row 1
- `frontend/src/app/analytics/pe-reviewed/page.tsx` — added Segment FilterBadge in Row 1

**Segment values**: NSE_EQ, NSE_SME, BSE_EQ, BSE_SME (static list, derived from series data in stocks table). Display labels use space instead of underscore (e.g. "NSE EQ"). Segment options are exchange-aware: BSE exchange shows only BSE_EQ/BSE_SME, NSE shows only NSE_EQ/NSE_SME. Changing exchange auto-clears mismatched segment.

### 2026-06-10: Sortable Date Column on PE Pages
**Problem**: No way to sort PE results by date — always newest first.

**Solution**: Clickable Date column header in PETable with 3-state toggle: default (DESC) → ASC → DESC → back to default.

**Files modified**:
- `backend/app/routers/pe_analysis.py` — added `sort_by` + `sort_dir` query params. Whitelist approach: only `date` → `COALESCE(announcement_date, created_at)` allowed. Default remains DESC.
- `frontend/src/lib/api.ts` — added `sort_by`, `sort_dir` to `fetchPEAnalysis` params
- `frontend/src/components/PETable.tsx` — `sortDir` state (null/asc/desc), Date header clickable with ArrowUp/ArrowDown/ArrowUpDown icons, resets page on sort change. Sort params passed to API only when active.
