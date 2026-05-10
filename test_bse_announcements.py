"""
BSE Announcements Test Script
- fetch_all_announcements(): Fetches ALL announcements for today (all categories), paginated
- fetch_result_announcements(): Fetches only 'Result' category announcements for today
- Prints category list and counts
"""

from bse import BSE
from bse.constants import CATEGORY
from datetime import datetime
import pathlib
import json

DIR = pathlib.Path(__file__).parent
BSE_DIR = DIR / "bse_downloads"
BSE_DIR.mkdir(exist_ok=True)


def fetch_all_announcements():
    """Fetch ALL announcements for today across all pages. No category filter."""
    today = datetime.now()
    all_rows = []
    with BSE(str(BSE_DIR)) as bse:
        page = 1
        total_count = 0
        while True:
            res = bse.announcements(page_no=page, from_date=today, to_date=today, segment="equity")
            table = res.get("Table", [])
            if not table:
                break
            if page == 1:
                total_count = res["Table1"][0]["ROWCNT"]
                print(f"Total announcements reported by BSE: {total_count}")
            all_rows.extend(table)
            pct = round(len(all_rows) / total_count * 100, 2) if total_count else 0
            print(f"  Page {page}: fetched {len(table)} rows ({pct}%)", flush=True)
            if len(all_rows) >= total_count:
                break
            page += 1
    return all_rows


def fetch_result_announcements():
    """Fetch only 'Result' category announcements for today across all pages."""
    today = datetime.now()
    result_rows = []
    with BSE(str(BSE_DIR)) as bse:
        page = 1
        total_count = 0
        while True:
            res = bse.announcements(
                page_no=page,
                from_date=today,
                to_date=today,
                segment="equity",
                category=CATEGORY.RESULT,
            )
            table = res.get("Table", [])
            if not table:
                break
            if page == 1:
                total_count = res["Table1"][0]["ROWCNT"]
                print(f"Total RESULT announcements reported by BSE: {total_count}")
            result_rows.extend(table)
            pct = round(len(result_rows) / total_count * 100, 2) if total_count else 0
            print(f"  Page {page}: fetched {len(table)} rows ({pct}%)", flush=True)
            if len(result_rows) >= total_count:
                break
            page += 1
    return result_rows


if __name__ == "__main__":
    print("=" * 60)
    print("BSE CATEGORY LIST")
    print("=" * 60)
    categories = {
        "AGM":           CATEGORY.AGM,
        "BOARD_MEETING": CATEGORY.BOARD_MEETING,
        "UPDATE":        CATEGORY.UPDATE,
        "ACTION":        CATEGORY.ACTION,
        "INSIDER":       CATEGORY.INSIDER,
        "NEW_LISTING":   CATEGORY.NEW_LISTING,
        "RESULT":        CATEGORY.RESULT,
        "OTHERS":        CATEGORY.OTHERS,
    }
    for key, val in categories.items():
        print(f"  CATEGORY.{key:<15} = '{val}'")

    print("\n" + "=" * 60)
    print(f"FETCHING ALL ANNOUNCEMENTS FOR {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 60)
    all_ann = fetch_all_announcements()
    print(f"\nTotal ALL announcements fetched: {len(all_ann)}")

    print("\n" + "=" * 60)
    print(f"FETCHING RESULT ANNOUNCEMENTS FOR {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 60)
    result_ann = fetch_result_announcements()
    print(f"\nTotal RESULT announcements fetched: {len(result_ann)}")

    if result_ann:
        print("\n" + "-" * 60)
        print("RESULT ANNOUNCEMENTS (first 10):")
        print("-" * 60)
        for i, row in enumerate(result_ann[:10], 1):
            symbol = row.get("SCRIP_CD", "?")
            name = row.get("SLONGNAME", "?")
            headline = row.get("HEADLINE") or row.get("NEWSSUB", "?")
            dt = row.get("DT_TM", "?")
            print(f"  {i}. [{symbol}] {name}")
            print(f"     {headline}")
            print(f"     Date: {dt}")
            print()
