# Quarterly Results - Implementation Guide

> **Delete this file after implementation is complete.**

---

## Overview

New `quarterly_results` system separate from Feed's `financial_metrics` table.
- One row per stock per quarter with BOTH standalone + consolidated as JSON
- Historical tracking across quarters
- Hybrid DB: denormalized EPS columns + full JSON blobs
- Model: `gpt-4o-mini` (no change)
- Quarter mapping: Jun→Q1, Sep→Q2, Dec→Q3, Mar→Q4 (Indian FY)

---

## Phase 1: DB Table (`nse_url_test.py`)

### Location: `init_db()` function (~line 642)

```sql
CREATE TABLE IF NOT EXISTS quarterly_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_symbol TEXT NOT NULL,
    company_name TEXT,
    quarter TEXT NOT NULL,
    financial_year TEXT NOT NULL,
    period_ended TEXT,

    eps_basic_standalone REAL,
    eps_diluted_standalone REAL,
    eps_basic_consolidated REAL,
    eps_diluted_consolidated REAL,

    standalone_data TEXT,
    consolidated_data TEXT,
    raw_ai_response TEXT,

    source_pdf_url TEXT,
    source_message_id INTEGER,
    exchange TEXT,
    units TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(stock_symbol, quarter, financial_year),
    FOREIGN KEY (source_message_id) REFERENCES messages(id)
);
CREATE INDEX IF NOT EXISTS idx_qr_symbol ON quarterly_results(stock_symbol);
CREATE INDEX IF NOT EXISTS idx_qr_quarter_fy ON quarterly_results(quarter, financial_year);
```

### UPSERT pattern:
```sql
INSERT INTO quarterly_results (...) VALUES (...)
ON CONFLICT(stock_symbol, quarter, financial_year)
DO UPDATE SET
    standalone_data = excluded.standalone_data,
    consolidated_data = excluded.consolidated_data,
    eps_basic_standalone = excluded.eps_basic_standalone,
    eps_diluted_standalone = excluded.eps_diluted_standalone,
    eps_basic_consolidated = excluded.eps_basic_consolidated,
    eps_diluted_consolidated = excluded.eps_diluted_consolidated,
    raw_ai_response = excluded.raw_ai_response,
    updated_at = excluded.updated_at
```

---

## Phase 2: Multi-Page OCR (`async_ocr_from_image.py`)

### Problem
`process_ocr_from_images_async()` returns on FIRST page with all 5 keywords.
Quarterly PDFs have Standalone (page 1) + Consolidated (page 2).

### Solution
New function: `process_ocr_all_financial_pages_async(image_paths)`
- Scans ALL pages, collects every page with >= 3/5 financial keywords
- Returns ALL financial pages' text + image paths
- Does NOT return early

### Returns:
```python
{
    "financial_texts": [page1_text, page2_text, ...],
    "all_pages_text": "combined",
    "financial_pages": [page_info_list],
    "detected_image_paths": [all_financial_page_images],
    "total_pages": N
}
```

### Existing function stays unchanged (Feed backward compatibility).

---

## Phase 3: AI Prompt (`async_ocr_from_image.py`)

### New function: `analyze_quarterly_results_async(financial_text, encoded_images)`

Separate from existing `analyze_financial_metrics_async` (Feed stays untouched).

### Prompt extracts:
```json
{
    "company_name": "Vasudhagama Enterprises Limited",
    "quarter": "Q1",
    "financial_year": "2025",
    "period_ended": "30.06.2025",
    "units": "lakhs",
    "standalone": {
        "revenue_from_operations": 550.79,
        "other_income": null,
        "total_income": 550.79,
        "total_expenses": 492.26,
        "profit_before_exceptional": 58.53,
        "exceptional_items": null,
        "profit_before_tax": 58.53,
        "tax_expense": 14.07,
        "profit_after_tax": 44.46,
        "profit_attributable_to_minority": null,
        "other_comprehensive_income": null,
        "total_comprehensive_income": 44.46,
        "paid_up_equity_share_capital": 169.64,
        "face_value": 1,
        "eps_basic": 0.26,
        "eps_diluted": 0.26
    },
    "consolidated": { "...same structure..." },
    "historical_quarters": [
        {
            "period_ended": "31.03.2025",
            "quarter": "Q4",
            "financial_year": "2025",
            "standalone": { "...same..." },
            "consolidated": { "...same..." }
        }
    ]
}
```

### Quarter mapping in prompt:
- June ending → Q1
- September ending → Q2
- December ending → Q3
- March ending → Q4

---

## Phase 4: Processing Pipeline (`nse_url_test.py`)

### New function: `process_quarterly_results(ai_response, stock_symbol, message_id, pdf_url, exchange)`

1. Parse AI response
2. UPSERT current quarter into `quarterly_results`
3. Loop `historical_quarters` → UPSERT each
4. Extract EPS into denormalized columns from JSON
5. Store `raw_ai_response` as-is
6. Broadcast via WebSocket `{"type": "quarterly_results", ...}`

### Integration points (2 places):
- `process_ca_data()` ~line 2092-2103 (NSE flow)
- `process_bse_ca_data()` ~line 2239-2249 (BSE flow)

Both currently call `main_ocr_async()` → `process_financial_metrics()`.
Add parallel call: same OCR result → `process_quarterly_results()`.

### Flow:
```
result_concall keyword match →
  main_ocr_async(pdf_url) →
    process_financial_metrics()     ← existing (Feed)
    process_quarterly_results()     ← NEW (Analytics)
```

---

## Phase 5: API Endpoints (`nse_url_test.py`)

### `GET /api/quarterly_results`
- Params: `symbol` (optional), `financial_year` (optional), `limit`
- Returns all quarterly_results rows
- JSON parses standalone_data / consolidated_data before returning

### `GET /api/quarterly_results/{symbol}`
- All quarters for one stock, ordered by FY desc, quarter desc

### `GET /api/pe_analysis`
- Joins quarterly_results EPS with live price (from quotes)
- Returns: symbol, quarter, FY, eps_basic_s, eps_diluted_s, eps_basic_c, eps_diluted_c
- PE computation can be client-side or server-side

---

## Phase 6: Frontend (`static/index.html`, `static/js/dashboard.js`)

### Analytics > PE Analysis page:
- Replace placeholder with table
- Columns: Stock | Quarter | FY | EPS Basic (S) | EPS Diluted (S) | EPS Basic (C) | EPS Diluted (C)
- Toggle: Standalone / Consolidated view
- Expandable row: full details (revenue, PAT, PBT, etc.)
- PE column (formula provided later by user)
- Auto-refreshes on WebSocket `quarterly_results` message

---

## Migration Plan (Future - Historical Backfill)

### When ready to migrate existing `financial_metrics` → `quarterly_results`:
1. Query all from `financial_metrics`
2. For each row, map: period→quarter, year→financial_year
3. Store as standalone_data JSON (assume existing = standalone since only first page was detected)
4. EPS from existing `eps` column → `eps_basic_standalone` (no diluted data exists)
5. UPSERT into quarterly_results
6. One-time script, run via `/api/migrate_financial_metrics` endpoint

### NOT doing this now - start fresh going forward.

---

## Execution Order

| Step | Phases | Files Changed |
|------|--------|---------------|
| 1 | Phase 1 + 3 | `nse_url_test.py` (DB), `async_ocr_from_image.py` (prompt) |
| 2 | Phase 2 + 4 | `async_ocr_from_image.py` (OCR), `nse_url_test.py` (pipeline) |
| 3 | Phase 5 + 6 | `nse_url_test.py` (API), `static/index.html`, `static/js/dashboard.js` |

---

## Testing Checklist

- [ ] DB table created on startup
- [ ] UPSERT works (no duplicate rows for same stock+quarter+FY)
- [ ] Multi-page OCR collects both standalone + consolidated pages
- [ ] AI extracts both table types correctly
- [ ] Historical quarters from PDF columns stored
- [ ] API returns correct JSON with parsed standalone/consolidated
- [ ] Frontend renders PE Analysis table
- [ ] WebSocket updates in real-time
- [ ] Existing Feed + financial_metrics flow unaffected
