"""
Test BSE Board Meeting category — fetch all, then filter for 'financial result' keyword.
"""

from bse import BSE
from bse.constants import CATEGORY
from datetime import datetime
import pathlib

DIR = pathlib.Path(__file__).parent
BSE_DIR = DIR / "bse_downloads"
BSE_DIR.mkdir(exist_ok=True)


def fetch_board_meeting():
    today = datetime.now()
    all_rows = []
    with BSE(str(BSE_DIR)) as bse:
        page = 1
        total_count = 0
        while True:
            res = bse.announcements(
                page_no=page, from_date=today, to_date=today,
                segment="equity", category=CATEGORY.BOARD_MEETING,
            )
            table = res.get("Table", [])
            if not table:
                break
            if page == 1:
                total_count = res["Table1"][0]["ROWCNT"]
                print(f"BSE reports {total_count} Board Meeting announcements")
            all_rows.extend(table)
            pct = round(len(all_rows) / total_count * 100, 2) if total_count else 0
            print(f"  Page {page}: {len(table)} rows ({pct}%)", flush=True)
            if len(all_rows) >= total_count:
                break
            page += 1
    return all_rows


if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")

    print("=" * 70)
    print(f"BSE BOARD MEETING ANNOUNCEMENTS — {today_str}")
    print("=" * 70)

    rows = fetch_board_meeting()
    print(f"\nTotal Board Meeting announcements: {len(rows)}")

    # Filter: include "financial result" keyword, exclude "board meeting intimation"
    matched = []
    skipped_intimation = 0
    skipped_no_keyword = 0
    for row in rows:
        desc = " ".join([
            str(row.get("HEADLINE") or ""),
            str(row.get("NEWSSUB") or ""),
            str(row.get("SUBCATNAME") or ""),
        ]).lower()
        if "financial result" not in desc:
            skipped_no_keyword += 1
            continue
        if "board meeting intimation" in desc:
            skipped_intimation += 1
            continue
        matched.append(row)

    print(f"\nMatched (financial result + not intimation): {len(matched)}")
    print(f"Skipped - no 'financial result' keyword: {skipped_no_keyword}")
    print(f"Skipped - 'board meeting intimation': {skipped_intimation}")
    print(f"Total skipped: {skipped_no_keyword + skipped_intimation}")

    if matched:
        print("\n" + "-" * 70)
        print(f"FINANCIAL RESULT MATCHES ({len(matched)}):")
        print("-" * 70)
        for i, row in enumerate(matched, 1):
            symbol = row.get("SCRIP_CD", "?")
            name = row.get("SLONGNAME", "?")
            headline = row.get("HEADLINE") or row.get("NEWSSUB", "?")
            att = row.get("ATTACHMENTNAME") or "-"
            dt = row.get("DT_TM", "?")
            print(f"  {i}. [{symbol}] {name}")
            print(f"     {headline}")
            print(f"     Attachment: {att}")
            print(f"     Date: {dt}")
            print()
