"""
BSE Corporate Announcements fetch - Simple test script.
Reference: https://bennythadikaran.github.io/BseIndiaApi/usage.html#corporate-filings
"""
import json
from pathlib import Path

from bse import BSE

DOWNLOAD_FOLDER = Path(__file__).parent / "files" / "bse_downloads"
OUTPUT_FILE = Path(__file__).parent / "files" / "bse_corporate.json"


def main():
    DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    with BSE(DOWNLOAD_FOLDER) as bse:
        data = bse.announcements(page_no=1, segment="equity")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"BSE data saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
