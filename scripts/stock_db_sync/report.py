"""
Generate a detailed dry-run report of planned stock DB changes.
"""

from datetime import datetime
from .merger import DiffResult


def generate_report(diff: DiffResult) -> str:
    lines: list[str] = []

    lines.append("=" * 80)
    lines.append("  STOCK DB SYNC — DRY-RUN REPORT")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 80)

    lines.append("")
    lines.append(f"  DB rows (current):       {diff.db_rows_total}")
    lines.append(f"  Canonical stocks (target): {diff.canonical_total}")

    # Merges
    lines.append("")
    lines.append("-" * 80)
    lines.append(f"  PHASE A: MERGE DUPLICATES — {len(diff.merges)} pairs")
    lines.append("-" * 80)
    if diff.merges:
        lines.append("")
        lines.append(f"  {'NSE Symbol':<20} {'BSE Scrip':<12} {'Company':<40} ISIN")
        lines.append(f"  {'─'*20} {'─'*12} {'─'*40} {'─'*15}")
        for m in diff.merges[:50]:
            lines.append(
                f"  {m.keep_symbol:<20} {m.delete_symbol:<12} "
                f"{m.company_name[:40]:<40} {m.isin}"
            )
        if len(diff.merges) > 50:
            lines.append(f"  ... and {len(diff.merges) - 50} more")
        lines.append("")
        lines.append("  Action: Keep NSE row, move quarterly_results/insights refs, delete BSE row.")
    else:
        lines.append("  No duplicate merges needed.")

    # Updates
    lines.append("")
    lines.append("-" * 80)
    lines.append(f"  PHASE B: UPDATE EXISTING — {len(diff.updates)} rows")
    lines.append("-" * 80)
    if diff.updates:
        col_counts: dict[str, int] = {}
        for u in diff.updates:
            for col in u.changes:
                col_counts[col] = col_counts.get(col, 0) + 1
        lines.append("")
        lines.append("  Columns being updated:")
        for col, cnt in sorted(col_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {col:<20} {cnt:>5} rows")

        lines.append("")
        lines.append("  Sample updates (first 20):")
        lines.append(f"  {'Symbol':<20} {'Columns Changed'}")
        lines.append(f"  {'─'*20} {'─'*50}")
        for u in diff.updates[:20]:
            cols = ", ".join(u.changes.keys())
            lines.append(f"  {u.db_symbol:<20} {cols}")
        if len(diff.updates) > 20:
            lines.append(f"  ... and {len(diff.updates) - 20} more")
    else:
        lines.append("  No updates needed.")

    # Inserts
    lines.append("")
    lines.append("-" * 80)
    lines.append(f"  PHASE C: INSERT NEW — {len(diff.inserts)} stocks")
    lines.append("-" * 80)
    if diff.inserts:
        seg_counts: dict[str, int] = {}
        for ins in diff.inserts:
            seg = ins.stock.market_segment or "UNKNOWN"
            seg_counts[seg] = seg_counts.get(seg, 0) + 1
        lines.append("")
        lines.append("  By market segment:")
        for seg, cnt in sorted(seg_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {seg:<15} {cnt:>5}")

        lines.append("")
        lines.append("  Sample inserts (first 20):")
        lines.append(f"  {'Symbol':<20} {'Segment':<12} {'Sector':<20} {'Company'}")
        lines.append(f"  {'─'*20} {'─'*12} {'─'*20} {'─'*30}")
        for ins in diff.inserts[:20]:
            s = ins.stock
            sym = s.nse_symbol or s.bse_scrip_code
            lines.append(
                f"  {sym:<20} {s.market_segment:<12} "
                f"{(s.sector or '-')[:20]:<20} {(s.company_name or '-')[:30]}"
            )
        if len(diff.inserts) > 20:
            lines.append(f"  ... and {len(diff.inserts) - 20} more")
    else:
        lines.append("  No new stocks to insert.")

    # Summary
    lines.append("")
    lines.append("-" * 80)
    lines.append("  SUMMARY")
    lines.append("-" * 80)
    final_count = (
        diff.db_rows_total
        - len(diff.merges)  # deleted duplicates
        + len(diff.inserts)
    )
    lines.append(f"  Current DB rows:     {diff.db_rows_total}")
    lines.append(f"  Duplicates removed:  {len(diff.merges)}")
    lines.append(f"  Rows updated:        {len(diff.updates)}")
    lines.append(f"  New rows inserted:   {len(diff.inserts)}")
    lines.append(f"  Expected final rows: {final_count}")
    lines.append("")
    lines.append("  To apply: python -m scripts.stock_db_sync.sync_stocks --apply")
    lines.append("=" * 80)

    return "\n".join(lines)
