# Future: Kotak Neo Scrip Master — Daily Auto-Sync

> **Status**: Deferred — Kotak Neo API not returning master files as expected.  
> **Current workaround**: Manual Excel import for exchange tokens.  
> **Implement when**: Kotak Neo master CSV download URL/API is confirmed working.

---

## Goal

Auto-download NSE + BSE scrip master files from Kotak Neo daily, parse them, and sync `exchange_token` into the `stocks` master table. This enables live CMP fetch → PE calculation in Analytics.

---

## Database Changes (already partially done)

Add to `stocks` table:
```sql
ALTER TABLE stocks ADD COLUMN nse_token INTEGER;
ALTER TABLE stocks ADD COLUMN bse_token INTEGER;
```

- `nse_token`: Kotak exchange token for NSE (`nse_cm|{token}`)
- `bse_token`: Kotak exchange token for BSE (`bse_cm|{token}`)
- A stock can have both (listed on NSE + BSE)

---

## Step 1: Determine Download Method

Kotak Neo provides scrip master files. Need to confirm:

- **URL pattern**: e.g. `https://lapi.kotaksecurities.com/scripmaster/nse_cm.csv`
- **Auth required?**: May need access_token from `kotak_session.json`
- **File format**: CSV with columns like `exchange_token`, `trading_symbol`, `isin`, `series`, `lot_size`, etc.
- **Refresh frequency**: Updated daily by Kotak (new listings, token changes)

### How to find the URL
1. Check Kotak Neo API docs / developer portal
2. Check `neo_login/` folder for any scrip master references
3. Ask Kotak support for the scrip master download endpoint
4. Alternatively: download manually from Kotak Neo web terminal → automate later

---

## Step 2: Daily Download Task

```
async def download_scrip_master():
    1. Load Kotak session (access_token, base_url)
    2. GET {base_url}/scrip-master/nse_cm.csv → save to files/nse_cm_master.csv
    3. GET {base_url}/scrip-master/bse_cm.csv → save to files/bse_cm_master.csv
    4. If session expired → log warning, skip (use cached file)
```

Schedule: Run once at startup + daily at a fixed time (e.g. 8:00 AM IST before market open).

---

## Step 3: Parse + Sync to `stocks` Table

```
async def sync_scrip_master_to_stocks():
    1. Read nse_cm_master.csv
    2. For each row:
       - symbol = row['trading_symbol'] (uppercase, stripped)
       - token  = row['exchange_token']
       - isin   = row['isin']
    3. Match to stocks table:
       - Primary match: stocks.symbol == symbol → UPDATE nse_token
       - Fallback match: stocks.isin == isin → UPDATE symbol + nse_token (handles renames)
    4. If no match → INSERT new stock (auto-grow master)
    5. Repeat for bse_cm_master.csv → update bse_token
    6. Mark stocks as is_active=0 if symbol disappears from ALL master files (delisted)
```

### Edge Cases
| Case | Handling |
|------|----------|
| Symbol renamed | ISIN stays same → match by ISIN, update symbol |
| Token changed | Daily sync overwrites → always latest |
| New IPO | Appears in master CSV → auto-inserted |
| Delisted | Missing from master → mark `is_active = 0` |
| Kotak session expired | Skip download, use last cached file |

---

## Step 4: Wire into PE Analysis

Once `stocks.nse_token` is populated:

```python
# In /api/pe_analysis endpoint:
1. Get all stocks with quarterly data (existing query)
2. Collect nse_token for each stock
3. Batch call Kotak quote API: nse_cm|{token} for all
4. Map CMP (close price) back to each stock
5. Compute PE = CMP / FY_EPS
6. Return CMP + PE in response
```

No client-side calculation needed — everything server-side.

---

## Step 5: PE History Snapshots (Future)

New table:
```sql
CREATE TABLE pe_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id INTEGER REFERENCES stocks(id),
    snapshot_date TEXT NOT NULL,
    cmp REAL,
    fy_eps REAL,
    pe REAL,
    quarter TEXT,
    financial_year TEXT,
    UNIQUE(stock_id, snapshot_date)
);
```

- Store one snapshot per stock per day
- Enables: PE trend charts, YoY comparison, sector PE averages
- Trigger: after successful CMP fetch in PE analysis

---

## Current Workaround

Until Kotak Neo master sync is automated:

1. **Manually download** Kotak scrip master Excel/CSV
2. **Import** via endpoint or script → populates `nse_token` / `bse_token` in `stocks`
3. PE Analysis uses these tokens to fetch live CMP

The import endpoint (`POST /api/import_scrip_master`) accepts the Excel file and syncs tokens.

---

## Files to Modify (When Implementing)

| File | Changes |
|------|---------|
| `nse_url_test.py` | `init_db()` migration for nse_token/bse_token, download task, sync function, PE endpoint update |
| `get_quote.py` | May need a lightweight `get_cmp_for_tokens(tokens)` helper |
| `stocks` table | New columns: `nse_token`, `bse_token`, `isin` |
| Scheduled task | Add daily scrip master download alongside existing fetch schedule |
