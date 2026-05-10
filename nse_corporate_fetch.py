"""
NSE Corporate Announcements fetch - Simple test script.
Uses nsepython.nsefetch() - pass NSE API URL directly.
"""
import json
from pathlib import Path

from nsepython import nsefetch

EQUITY_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"
SME_URL = "https://www.nseindia.com/api/corporate-announcements?index=sme"
OUTPUT_FILE = Path(__file__).parent / "files" / "nse_corporate.json"


def main():
    data = nsefetch(EQUITY_URL)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"NSE data saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
