# PE Page Deduplication & Data Issues Report

**Date:** 2026-06-01  
**Database:** `automation_trade` on container `trade_postgres`

---

## Summary of Current State

| Metric | Count |
|--------|-------|
| PE Pending rows | 3,038 |
| PE Reviewed rows | 3,400 |
| **Total quarterly_results** | **6,438** |
| Ghost pending rows (reviewed stock reappearing as pending) | **203** |
| Stocks with 3+ duplicate rows for same quarter | **13+** |
| Duplicate ISINs in stocks table | **9 ISINs (18 rows)** |
| Non-canonical valuation labels | **8 rows (3 labels)** |
| Lost reviewed rows (valuation set but invisible) | **0** |

---

## Issue 1: Ghost Pending Rows (203 rows) — CRITICAL

### What's happening

You review a stock (e.g. mark `500570` as `EXPENSIVE`), but it reappears in PE Pending the next day. This is the main bug you reported.

### Root cause

The unique constraint on `quarterly_results` is:

```
(stock_symbol, quarter, financial_year, announcement_date)
```

When a company files a **revised result** with a new `announcement_date`, it creates a **brand new row**. This new row has `valuation = NULL`, so it shows up as PE Pending — even though you already reviewed the earlier filing.

### Detailed example: stock `500570` lifecycle

```
Timeline for BSE scrip 500570, Q4 2025-26:

May 13 23:32 → Row 108775 CREATED (fetcher ingests Q4 result, extraction_status=completed)
May 14 16:32 → Row 116775 CREATED (company files REVISED result, new announcement_date)
May 14 19:04 → Row 108775 REVIEWED as EXPENSIVE (you review it in the UI)
                Row 116775 remains valuation=NULL → still shows in PE Pending!

Result: You reviewed the stock, but a newer row (filed just hours earlier) sits 
        in PE Pending with no valuation. The UI shows it as "not reviewed."
```

Full row data:

| id | stock_symbol | announcement_date | valuation | user_reviewed | extraction_status | created_at | reviewed_at |
|---|---|---|---|---|---|---|---|
| 108775 | 500570 | 2026-05-13 | EXPENSIVE | true | completed | May 13 23:32 | May 14 19:04 |
| 116775 | 500570 | 2026-05-14 | *(empty)* | false | completed | May 14 16:32 | *(null)* |

### How many are affected, by time gap

| Gap between filings | Ghost rows | Pattern |
|---|---|---|
| 0-1 days | 77 | Same-day or next-day revised filing |
| 2-3 days | 28 | Minor correction filed within a few days |
| 4-7 days | 35 | Delayed correction |
| 8+ days | 67 | Late revision (some up to 18 days later) |
| **Total** | **207** | *(some rows have multiple reviewed siblings)* |

### Which valuations are most affected

| Your original valuation | Ghost count |
|---|---|
| IGNORE | 103 |
| EXPENSIVE | 59 |
| CHEAP | 36 |
| FAIRLY_VALUED | 4 |
| INLINE | 4 |
| DONT TOUCH | 1 |

IGNORE stocks are the most common ghosts (103 of 207) — you marked them as not interesting, but the revised filing brought them back.

### Worst offenders: stocks with 3+ rows for the same quarter

These stocks have been filed/revised multiple times, creating 3-5 rows:

| Stock | Rows | Dates | Valuations |
|---|---|---|---|
| BANSALWIRE | 5 | May 5, 6, 14 + 2 with NULL dates | EXPENSIVE, EXPENSIVE, IGNORE, PENDING, PENDING |
| TOKYOPLAST | 5 | May 7, 13, 14 + 2 with NULL dates | PENDING, IGNORE, PENDING, PENDING, IGNORE |
| BHAGYANGR | 4 | May 8, 14 + 2 with NULL dates | PENDING, PENDING, PENDING, EXPENSIVE |
| PARKHOSPS | 4 | May 12, 15, 22, 25 | PENDING, PENDING, EXPENSIVE, PENDING |
| SHREDIGCEM | 4 | May 23, 29 + 2 with NULL dates | PENDING, PENDING, PENDING, EXPENSIVE |
| STLTECH | 4 | May 5, 14 + 2 with NULL dates | PENDING, PENDING, EXPENSIVE, PENDING |
| UEL | 4 | May 8, 19 + 2 with NULL dates | PENDING, PENDING, PENDING, IGNORE |
| 512361 | 3 | May 15, 19, 23 | EXPENSIVE, PENDING, PENDING |
| 544667 | 3 | May 7, 19, 20 | CHEAP, PENDING, PENDING |
| EASEMYTRIP | 3 | May 13, 26, 31 | IGNORE, IGNORE, PENDING |

Note: Some rows have `NULL` announcement dates — these are also creating duplicates because `NULL != NULL` in SQL, so the unique constraint doesn't prevent them.

### Why `DEDUP_ENABLED = False` makes it worse

In `backend/app/routers/pe_analysis.py` line 27:

```python
DEDUP_ENABLED = False
```

When `True`, the PE Pending query had a `NOT EXISTS` clause to exclude rows where the same stock+quarter+FY already had a reviewed counterpart. With it `False`, every row is shown independently — all 203+ ghost rows appear in PE Pending.

### Impact

- You waste time re-reviewing stocks you've already seen
- PE Pending count (3,038) is inflated by ~203 ghost rows
- Actual unique pending stocks to review ≈ **2,835**
- Stocks like BANSALWIRE/TOKYOPLAST show up 3-4 times in pending

### How to reproduce

1. Open PE Pending page
2. Search for `EASEMYTRIP` — it will appear as pending
3. But you already reviewed it as IGNORE twice (May 13, May 26)
4. The May 31 revised filing created a new ghost row

### Fix plan (3 layers)

**Layer 1 — API query fix (immediate):** Add a simple `NOT EXISTS` to the PE Pending query that hides rows when a reviewed sibling exists for the same `(stock_symbol, quarter, financial_year)`. No cross-exchange symbol resolution needed — just match on `stock_symbol` directly. This is simpler and faster than the old `DEDUP_ENABLED` approach.

**Layer 2 — Ingest fix (prevent future ghosts):** When the fetcher/worker inserts a new row with the same `(stock_symbol, quarter, FY)`, check if a reviewed row already exists. If yes, either:
- Copy `valuation`/`user_reviewed`/`reviewed_at` to the new row, OR
- Update the existing row's data (EPS, PDF URL, announcement_date) instead of creating a new one

**Layer 3 — One-time DB cleanup:** For the existing 203 ghost rows, carry forward the valuation from the reviewed sibling to the newest row, then delete the older duplicate rows. Keep only the latest announcement per `(stock_symbol, quarter, FY)`.

---

## Issue 2: Non-Canonical Valuation Labels (8 rows) — MEDIUM PRIORITY

### What's happening

3 valuation labels don't follow the standard `UPPER_SNAKE_CASE` format:

| Current Value | Count | Should Be | Action |
|---|---|---|---|
| `FAIRLY VALUED` | 4 | `FAIRLY_VALUED` | Normalize (same meaning, just formatting) |
| `DONT TOUCH` | 3 | Keep as custom | Create as custom valuation option |
| `UNDERVALUED` | 1 | Keep as custom | Create as custom valuation option |

### Fix commands (run in psql)

**Step 1:** Normalize `FAIRLY VALUED` → `FAIRLY_VALUED`:

```sql
UPDATE quarterly_results 
SET valuation = 'FAIRLY_VALUED', updated_at = NOW()
WHERE valuation = 'FAIRLY VALUED';
```

**Step 2:** Register `DONT_TOUCH` as a custom valuation (normalize the space):

```sql
UPDATE quarterly_results 
SET valuation = 'DONT_TOUCH', updated_at = NOW()
WHERE valuation = 'DONT TOUCH';

INSERT INTO custom_valuations (value, label, tone) 
VALUES ('DONT_TOUCH', 'Don''t Touch', 'bearish')
ON CONFLICT DO NOTHING;
```

**Step 3:** Register `UNDERVALUED` as a custom valuation:

```sql
INSERT INTO custom_valuations (value, label, tone) 
VALUES ('UNDERVALUED', 'Undervalued', 'bullish')
ON CONFLICT DO NOTHING;
```

**Verify after:**

```sql
SELECT valuation, COUNT(*) AS cnt
FROM quarterly_results
WHERE valuation IS NOT NULL AND valuation != ''
GROUP BY valuation ORDER BY cnt DESC;
```

Expected: No more `FAIRLY VALUED` or `DONT TOUCH` (with spaces). `FAIRLY_VALUED` count should be 30. `DONT_TOUCH` count should be 3. `UNDERVALUED` stays as 1.

---

## Issue 3: Duplicate ISINs in Stocks Table (9 ISINs, 18 rows) — MEDIUM PRIORITY

### What's happening

9 companies have 2 entries in the `stocks` table with the same ISIN but different symbols. All are marked as `exchange = 'NSE'`.

### Data

| ISIN | Symbol 1 (NSE) | Symbol 2 (BSE scrip / old name) | Stock IDs | Likely Reason |
|---|---|---|---|---|
| INE019J01013 | SASTASUNDR | 533259 | 14059, 10274 | BSE scrip stored as NSE |
| INE0Q9W01015 | FAALCON | 544164 | 15207, 11736 | BSE scrip stored as NSE |
| INE131C01011 | ICSA | 500068 | 13158, 7333 | BSE scrip stored as NSE |
| INE133A01011 | AKZOINDIA | JSWDULUX | 12343, 13313 | Company renamed |
| INE214T01019 | LTIM | LTM | 13473, 13474 | Symbol renamed |
| INE243B01016 | PADMALAYAT | 532350 | 16162, 9846 | BSE scrip stored as NSE |
| INE286H01012 | VISASTEEL | 532721 | 14509, 10020 | BSE scrip stored as NSE |
| INE374C01017 | RAJASPETRO | 506975 | 17130, 7895 | BSE scrip stored as NSE |
| INE688J01023 | EXCEL | LANDSMILL | 12892, 13431 | Symbol renamed |

### Root cause

- BSE stocks were imported with `exchange = 'NSE'` instead of `'BSE'`
- Company/symbol renames created new entries without merging old ones

### Impact

- Currently **NOT** causing PE page duplicates (verified: no `quarterly_results` data exists for both symbols of any pair)
- But if results are fetched for both symbols in the future, it will create visible duplicates
- Dirty data in the stocks registry

### Fix: Merge script needed

For each duplicate ISIN pair, merge the two `stocks` rows into one (keep the one with more data, update `stock_id` FK in `quarterly_results`).

---

## Issue 4: NULL announcement_dates creating extra duplicates — MEDIUM PRIORITY

### What's happening

762 rows (12% of all data) have `NULL` `announcement_date`. Since `NULL != NULL` in SQL, the unique constraint `(stock_symbol, quarter, financial_year, announcement_date)` does NOT prevent multiple NULL-date rows for the same stock+quarter+FY.

### Scale

| Metric | Count |
|---|---|
| Total NULL-date rows | **762** |
| NULL-date rows in PE Pending | **469** |
| NULL-date rows in PE Reviewed | **293** |
| NULL-date rows that are duplicates (have a sibling with a date) | **283** |

### Root cause: Legacy data from SQLite migration

**Current code NEVER creates NULL dates.** All fetchers (NSE, BSE), OCR extractor, and worker tasks have fallbacks to use today's date when no date is available. No recent git changes (last 5 days) affected date handling.

The NULL-date rows were created by:

1. **Old monolith** (`_archive/legacy_scripts/nse_url_test.py`) — inserted rows with `announcement_date=None`
2. **SQLite → Postgres migration** (`scripts/migrate_sqlite_to_postgres.py`) — copied NULLs as-is
3. **Migration 005** — normalized only non-NULL dates, skipped NULL rows

When current extraction completes, it creates a NEW row with `(symbol, quarter, FY, <date>)` — the old NULL row is a different unique key and survives untouched.

### Example: BANSALWIRE Q4 2025-26

| Row ID | announcement_date | valuation | Origin |
|---|---|---|---|
| 3454 | NULL | PENDING | Legacy SQLite |
| 3459 | NULL | PENDING | Legacy SQLite |
| 6392 | 2026-05-05 | EXPENSIVE | Current code |
| 6501 | 2026-05-06 | EXPENSIVE | Current code |
| 117260 | 2026-05-14 | IGNORE | Current code |

5 rows for the same stock+quarter+FY. The two NULL-date rows are legacy ghosts.

### Fix needed

- **One-time cleanup:** Delete or backfill NULL-date rows where a dated sibling exists for the same stock+quarter+FY
- **Prevent recurrence:** Add partial unique index: `CREATE UNIQUE INDEX ON quarterly_results (stock_symbol, quarter, financial_year) WHERE announcement_date IS NULL`
- **Long-term:** Add `NOT NULL DEFAULT NOW()` constraint on `announcement_date` after cleanup

---

## Issue 5: No Data Was Deleted — CONFIRMED

- PE Reviewed count: **3,400** rows — all reviews intact
- Issue 4 edge case (lost rows): **0 rows** — no stock has valuation set but is invisible
- The `update_pe_analysis` endpoint correctly sets `user_reviewed = TRUE` + `reviewed_at = NOW()`
- Ghost rows are NEW rows (different `id`, different `announcement_date`) — originals untouched

### Valuation breakdown (all 3,400 reviewed)

| Valuation | Count |
|---|---|
| IGNORE | 2,029 (59.7%) |
| EXPENSIVE | 870 (25.6%) |
| CHEAP | 399 (11.7%) |
| INLINE | 68 (2.0%) |
| FAIRLY_VALUED | 26 (0.8%) |
| FAIRLY VALUED | 4 *(needs normalization)* |
| DONT TOUCH | 3 *(needs custom registration)* |
| UNDERVALUED | 1 *(needs custom registration)* |

---

## Queries for Data Export

### Export all PE Reviewed rows to CSV (run inside psql)

```sql
\copy (
  SELECT qr.id, qr.stock_symbol, qr.exchange, qr.quarter, qr.financial_year,
         qr.valuation, qr.pe, qr.cmp, qr.company_name, qr.user_reviewed,
         qr.extraction_status, qr.announcement_date, qr.reviewed_at,
         qr.recommendation, qr.target_price, qr.comments
  FROM quarterly_results qr
  WHERE qr.valuation IS NOT NULL AND qr.valuation != ''
  ORDER BY qr.reviewed_at DESC NULLS LAST, qr.id DESC
) TO '/tmp/pe_reviewed_export.csv' WITH CSV HEADER;
```

Then copy from container:
```bash
docker cp trade_postgres:/tmp/pe_reviewed_export.csv ./pe_reviewed_export.csv
```

### Export all ghost pending rows

```sql
\copy (
  SELECT p.id AS pending_id, p.stock_symbol, p.exchange, p.company_name,
         p.quarter, p.financial_year, p.announcement_date AS pending_date,
         r.id AS reviewed_id, r.announcement_date AS reviewed_date,
         r.valuation AS reviewed_valuation,
         (p.announcement_date - r.announcement_date) AS days_gap
  FROM quarterly_results p
  JOIN quarterly_results r
      ON r.stock_symbol = p.stock_symbol
      AND r.quarter = p.quarter
      AND r.financial_year = p.financial_year
      AND r.announcement_date != p.announcement_date
      AND (r.valuation IS NOT NULL AND r.valuation != '')
  WHERE (p.valuation IS NULL OR p.valuation = '')
  ORDER BY p.announcement_date DESC, p.stock_symbol
) TO '/tmp/ghost_pending_export.csv' WITH CSV HEADER;
```

---

## Complete Action Plan

| # | Priority | Task | What to change | Effort | Risk |
|---|---|---|---|---|---|
| 1 | CRITICAL | **Fix PE Pending query** — add `NOT EXISTS` to hide ghost rows where a reviewed sibling exists for same `(stock_symbol, quarter, FY)` | `pe_analysis.py` — add condition to `valuation_filter=pending` | Small | Low |
| 2 | CRITICAL | **One-time DB cleanup** — for existing 203 ghosts: carry forward valuation to newest row, delete older duplicates. Keep one row per `(stock_symbol, quarter, FY)` | One-time SQL script | Small | Low (reversible) |
| 3 | HIGH | **Fix ingest pipeline** — when fetcher inserts a row and a reviewed sibling already exists for same `(stock_symbol, quarter, FY)`, auto-carry-forward valuation | `ocr_extractor.py`, `nse_fetcher.py`, `bse_fetcher.py`, `worker/tasks/extraction.py` | Medium | Medium |
| 4 | HIGH | **Clean NULL-date rows** — delete or fix rows with `announcement_date IS NULL` that are creating extra duplicates | One-time SQL script | Small | Low |
| 5 | MEDIUM | **Normalize valuations** — fix 8 rows: `FAIRLY VALUED`→`FAIRLY_VALUED`, `DONT TOUCH`→`DONT_TOUCH`, register customs | SQL commands (see Issue 2 above) | Tiny | None |
| 6 | MEDIUM | **Merge 9 duplicate stocks** — merge stocks table entries sharing the same ISIN | One-time merge script | Small | Low |
| 7 | LOW | **Fix exchange field** — BSE-sourced stocks stored as `exchange='NSE'` | One-time SQL update | Tiny | None |

---

## How to Verify Fixes

After applying fixes, run these verification queries:

```sql
-- Should return 0 after fixing ghost pending (Issue 1)
SELECT COUNT(*) FROM quarterly_results p
WHERE (p.valuation IS NULL OR p.valuation = '')
  AND EXISTS (
    SELECT 1 FROM quarterly_results r
    WHERE r.stock_symbol = p.stock_symbol
      AND r.quarter = p.quarter
      AND r.financial_year = p.financial_year
      AND r.id != p.id
      AND (r.valuation IS NOT NULL AND r.valuation != '')
  );

-- Should return 0 duplicate rows per stock+quarter+FY
SELECT COUNT(*) FROM (
  SELECT stock_symbol, quarter, financial_year
  FROM quarterly_results
  GROUP BY stock_symbol, quarter, financial_year
  HAVING COUNT(*) > 1
) sub;

-- Should return 0 after merging duplicate stocks (Issue 3)
SELECT COUNT(*) FROM (
  SELECT isin FROM stocks
  WHERE isin IS NOT NULL AND isin != ''
  GROUP BY isin HAVING COUNT(*) > 1
) sub;

-- All valuations should be canonical UPPER_SNAKE_CASE (Issue 2)
SELECT valuation, COUNT(*) FROM quarterly_results
WHERE valuation IS NOT NULL AND valuation != ''
GROUP BY valuation ORDER BY COUNT(*) DESC;

-- PE Pending + PE Reviewed should equal total (no lost rows)
SELECT
    CASE WHEN valuation IS NULL OR valuation = '' THEN 'PENDING' ELSE 'REVIEWED' END AS status,
    COUNT(*)
FROM quarterly_results
GROUP BY status;
```
