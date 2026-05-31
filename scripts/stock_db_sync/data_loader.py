"""
Load and parse stock data from all three sources into a canonical format.

Sources:
  1. BSE_54Sector OVERALL.xlsx  (MASTER DATABASE sheet) -- sector classification
  2. truedata_nse_stocks.csv    -- NSE stocks with series, ISIN, tokens
  3. truedata_bse_stocks.csv    -- BSE stocks with series, ISIN, tokens
"""

import csv
from pathlib import Path
from dataclasses import dataclass, field

try:
    import openpyxl
except ImportError:
    raise SystemExit("openpyxl required: pip install openpyxl")


NSE_TARGET_SERIES = {"EQ", "BE", "SM", "ST"}
BSE_TARGET_SERIES = {"A", "B", "T", "X", "M", "MT"}


@dataclass
class CanonicalStock:
    isin: str
    company_name: str = ""
    nse_symbol: str = ""
    bse_scrip_code: str = ""
    nse_token: int | None = None
    bse_token: int | None = None
    nse_series: str = ""
    bse_series: str = ""
    market_segment: str = ""
    sector: str = ""
    industry_group: str = ""
    sub_sector: str = ""
    exchange: str = ""


def derive_market_segment(nse_series: str, bse_series: str) -> str:
    if nse_series in ("EQ", "BE"):
        return "NSE_EQ"
    if nse_series in ("SM", "ST"):
        return "NSE_SME"
    if bse_series in ("A", "B", "T", "X"):
        return "BSE_EQ"
    if bse_series in ("M", "MT"):
        return "BSE_SME"
    return ""


def derive_exchange(nse_symbol: str, bse_scrip_code: str) -> str:
    if nse_symbol and bse_scrip_code:
        return "NSE"  # prefer NSE for dual-listed
    if nse_symbol:
        return "NSE"
    return "BSE"


def load_truedata_nse(csv_path: str | Path) -> dict[str, CanonicalStock]:
    """Return {isin: CanonicalStock} for NSE stocks in target series."""
    result: dict[str, CanonicalStock] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            series = row.get("series", "").strip()
            if series not in NSE_TARGET_SERIES:
                continue
            isin = row.get("isin", "").strip().upper()
            if not isin:
                continue
            symbol = row.get("symbol", "").strip()
            token_str = row.get("token", "0").strip()
            token = int(token_str) if token_str.isdigit() and int(token_str) > 0 else None
            company = row.get("company", "") or row.get("underlying", "") or ""

            stock = result.get(isin)
            if stock is None:
                stock = CanonicalStock(isin=isin)
                result[isin] = stock

            stock.nse_symbol = symbol
            stock.nse_token = token
            stock.nse_series = series
            if company:
                stock.company_name = company.strip()

    return result


def load_truedata_bse(csv_path: str | Path) -> dict[str, CanonicalStock]:
    """Return {isin: CanonicalStock} for BSE stocks in target series."""
    result: dict[str, CanonicalStock] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            series = row.get("series", "").strip()
            if series not in BSE_TARGET_SERIES:
                continue
            isin = row.get("isin", "").strip().upper()
            if not isin:
                continue
            token_str = row.get("token", "0").strip()
            token = int(token_str) if token_str.isdigit() and int(token_str) > 0 else None
            scrip_code = str(token) if token else ""
            company = row.get("underlying", "") or row.get("company", "") or ""

            stock = result.get(isin)
            if stock is None:
                stock = CanonicalStock(isin=isin)
                result[isin] = stock

            stock.bse_series = series
            stock.bse_token = token
            stock.bse_scrip_code = scrip_code
            if company and not stock.company_name:
                stock.company_name = company.strip()

    return result


# Excel column indices (0-based) in MASTER DATABASE sheet
_COL_COMPANY = 1
_COL_BSE_CODE = 2
_COL_NSE_CODE = 3
_COL_ISIN = 4
_COL_SECTOR = 5
_COL_INDUSTRY_GROUP = 6
_COL_SUB_INDUSTRY = 8
_COL_EXCHANGE = 10


def load_excel(xlsx_path: str | Path) -> dict[str, dict]:
    """Return {isin: {company_name, bse_code, nse_code, sector, ...}} from Excel."""
    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    ws = wb["MASTER DATABASE"]
    result: dict[str, dict] = {}

    for row in ws.iter_rows(min_row=2, values_only=True):
        company = row[_COL_COMPANY]
        if not company:
            continue
        isin = str(row[_COL_ISIN]).strip().upper() if row[_COL_ISIN] else ""
        if not isin:
            continue
        result[isin] = {
            "company_name": str(company).strip(),
            "bse_code": str(int(row[_COL_BSE_CODE])) if row[_COL_BSE_CODE] else "",
            "nse_code": str(row[_COL_NSE_CODE]).strip().upper() if row[_COL_NSE_CODE] else "",
            "sector": str(row[_COL_SECTOR]).strip() if row[_COL_SECTOR] else "",
            "industry_group": str(row[_COL_INDUSTRY_GROUP]).strip() if row[_COL_INDUSTRY_GROUP] else "",
            "sub_industry": str(row[_COL_SUB_INDUSTRY]).strip() if row[_COL_SUB_INDUSTRY] else "",
            "exchange_listed": str(row[_COL_EXCHANGE]).strip() if row[_COL_EXCHANGE] else "",
        }

    wb.close()
    return result


def build_canonical_map(
    nse_csv: str | Path,
    bse_csv: str | Path,
    excel_path: str | Path,
) -> dict[str, CanonicalStock]:
    """
    Merge all three sources into a single {isin: CanonicalStock} map.
    Priority: Truedata for symbols/tokens/series, Excel for sectors.
    """
    nse_map = load_truedata_nse(nse_csv)
    bse_map = load_truedata_bse(bse_csv)
    excel_map = load_excel(excel_path)

    canonical: dict[str, CanonicalStock] = {}

    # Start with NSE data
    for isin, stock in nse_map.items():
        canonical[isin] = stock

    # Merge BSE data
    for isin, bse_stock in bse_map.items():
        existing = canonical.get(isin)
        if existing:
            existing.bse_series = bse_stock.bse_series
            existing.bse_token = bse_stock.bse_token
            existing.bse_scrip_code = bse_stock.bse_scrip_code
            if not existing.company_name and bse_stock.company_name:
                existing.company_name = bse_stock.company_name
        else:
            canonical[isin] = bse_stock

    # Enrich with Excel sector data
    for isin, excel_data in excel_map.items():
        existing = canonical.get(isin)
        if existing:
            if excel_data["sector"]:
                existing.sector = excel_data["sector"]
            if excel_data["industry_group"]:
                existing.industry_group = excel_data["industry_group"]
            if excel_data["sub_industry"]:
                existing.sub_sector = excel_data["sub_industry"]
            if not existing.company_name and excel_data["company_name"]:
                existing.company_name = excel_data["company_name"]
            if not existing.nse_symbol and excel_data["nse_code"]:
                existing.nse_symbol = excel_data["nse_code"]
            if not existing.bse_scrip_code and excel_data["bse_code"]:
                existing.bse_scrip_code = excel_data["bse_code"]
        else:
            # Stock in Excel but not in Truedata -- skip (not in target series)
            pass

    # Derive market_segment and exchange for every stock
    for stock in canonical.values():
        stock.market_segment = derive_market_segment(stock.nse_series, stock.bse_series)
        stock.exchange = derive_exchange(stock.nse_symbol, stock.bse_scrip_code)

    return canonical
