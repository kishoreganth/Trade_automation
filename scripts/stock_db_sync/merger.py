"""
Diff the canonical stock map against the current database and produce
structured change sets: merges, updates, inserts.
"""

from dataclasses import dataclass, field
from .data_loader import CanonicalStock


@dataclass
class DbRow:
    id: int
    symbol: str
    company_name: str
    exchange: str
    sector: str
    sub_sector: str
    isin: str
    nse_token: int | None
    bse_token: int | None
    nse_symbol: str
    bse_scrip_code: str
    nse_series: str
    bse_series: str
    market_segment: str
    industry_group: str
    is_active: bool


@dataclass
class MergeAction:
    """Merge a BSE duplicate row into the NSE row for the same company."""
    keep_id: int
    keep_symbol: str
    delete_id: int
    delete_symbol: str
    isin: str
    company_name: str


@dataclass
class UpdateAction:
    """Update an existing DB row with enriched data."""
    db_id: int
    db_symbol: str
    changes: dict  # column -> new_value


@dataclass
class InsertAction:
    """Insert a brand new stock."""
    stock: CanonicalStock


@dataclass
class DiffResult:
    merges: list[MergeAction] = field(default_factory=list)
    updates: list[UpdateAction] = field(default_factory=list)
    inserts: list[InsertAction] = field(default_factory=list)
    skipped_no_isin: int = 0
    db_rows_total: int = 0
    canonical_total: int = 0


def compute_diff(
    canonical: dict[str, CanonicalStock],
    db_rows: list[dict],
) -> DiffResult:
    """
    Compare canonical map (keyed by ISIN) with DB rows and produce a DiffResult.

    db_rows: list of dicts with keys matching DbRow fields.
    """
    result = DiffResult()
    result.canonical_total = len(canonical)
    result.db_rows_total = len(db_rows)

    # Index DB rows
    db_by_isin: dict[str, list[dict]] = {}
    db_by_symbol: dict[str, dict] = {}
    db_by_scrip: dict[str, dict] = {}  # bse scrip code string -> row

    for row in db_rows:
        sym = row["symbol"]
        db_by_symbol[sym] = row
        if sym.isdigit():
            db_by_scrip[sym] = row
        isin = row.get("isin") or ""
        if isin:
            db_by_isin.setdefault(isin, []).append(row)

    # Build a reverse lookup: for each DB row, find its ISIN from canonical
    # (since DB currently has 0 ISINs filled, we match by symbol)
    symbol_to_isin: dict[str, str] = {}
    scrip_to_isin: dict[str, str] = {}

    for isin, stock in canonical.items():
        if stock.nse_symbol:
            symbol_to_isin[stock.nse_symbol] = isin
        if stock.bse_scrip_code:
            scrip_to_isin[stock.bse_scrip_code] = isin

    # Phase 1: Identify merges (dual-listed stocks with two DB rows)
    merge_delete_ids: set[int] = set()

    for isin, stock in canonical.items():
        if not stock.nse_symbol or not stock.bse_scrip_code:
            continue

        nse_row = db_by_symbol.get(stock.nse_symbol)
        bse_row = db_by_scrip.get(stock.bse_scrip_code)

        if nse_row and bse_row and nse_row["id"] != bse_row["id"]:
            result.merges.append(MergeAction(
                keep_id=nse_row["id"],
                keep_symbol=nse_row["symbol"],
                delete_id=bse_row["id"],
                delete_symbol=bse_row["symbol"],
                isin=isin,
                company_name=stock.company_name,
            ))
            merge_delete_ids.add(bse_row["id"])

    # Phase 2: Identify updates for existing rows (not being deleted)
    matched_isins: set[str] = set()

    for isin, stock in canonical.items():
        # Find the DB row for this ISIN
        db_row = None
        if stock.nse_symbol and stock.nse_symbol in db_by_symbol:
            db_row = db_by_symbol[stock.nse_symbol]
        elif stock.bse_scrip_code and stock.bse_scrip_code in db_by_scrip:
            db_row = db_by_scrip[stock.bse_scrip_code]

        if db_row is None:
            continue
        if db_row["id"] in merge_delete_ids:
            # This is the BSE duplicate being deleted; the NSE row will be updated instead
            nse_row = db_by_symbol.get(stock.nse_symbol)
            if nse_row:
                db_row = nse_row
            else:
                continue

        matched_isins.add(isin)
        changes: dict[str, object] = {}

        # Always set these identity fields
        if stock.isin and (db_row.get("isin") or "") != stock.isin:
            changes["isin"] = stock.isin
        if stock.nse_symbol and (db_row.get("nse_symbol") or "") != stock.nse_symbol:
            changes["nse_symbol"] = stock.nse_symbol
        if stock.bse_scrip_code and (db_row.get("bse_scrip_code") or "") != stock.bse_scrip_code:
            changes["bse_scrip_code"] = stock.bse_scrip_code
        if stock.nse_token and db_row.get("nse_token") != stock.nse_token:
            changes["nse_token"] = stock.nse_token
        if stock.bse_token and db_row.get("bse_token") != stock.bse_token:
            changes["bse_token"] = stock.bse_token
        if stock.nse_series and (db_row.get("nse_series") or "") != stock.nse_series:
            changes["nse_series"] = stock.nse_series
        if stock.bse_series and (db_row.get("bse_series") or "") != stock.bse_series:
            changes["bse_series"] = stock.bse_series
        if stock.market_segment and (db_row.get("market_segment") or "") != stock.market_segment:
            changes["market_segment"] = stock.market_segment
        if stock.sector and (db_row.get("sector") or "") != stock.sector:
            changes["sector"] = stock.sector
        if stock.industry_group and (db_row.get("industry_group") or "") != stock.industry_group:
            changes["industry_group"] = stock.industry_group
        if stock.sub_sector and (db_row.get("sub_sector") or "") != stock.sub_sector:
            changes["sub_sector"] = stock.sub_sector
        if stock.company_name and not db_row.get("company_name"):
            changes["company_name"] = stock.company_name
        # Update exchange for dual-listed
        if stock.nse_symbol and stock.bse_scrip_code:
            if db_row.get("exchange") != "NSE":
                changes["exchange"] = "NSE"

        if changes:
            result.updates.append(UpdateAction(
                db_id=db_row["id"],
                db_symbol=db_row["symbol"],
                changes=changes,
            ))

    # Phase 3: Identify inserts (stocks in canonical but not in DB)
    for isin, stock in canonical.items():
        if isin in matched_isins:
            continue
        # Double-check it really doesn't exist by symbol
        if stock.nse_symbol and stock.nse_symbol in db_by_symbol:
            continue
        if stock.bse_scrip_code and stock.bse_scrip_code in db_by_scrip:
            continue
        result.inserts.append(InsertAction(stock=stock))

    return result
