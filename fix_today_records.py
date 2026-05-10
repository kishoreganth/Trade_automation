"""Fix today's records: set announcement_date from bse_announcements_log where missing."""
import asyncio, os, sys
sys.path.insert(0, 'backend')
os.environ.setdefault('ENV_FILE', '.env')
from app.database import get_db_session
from sqlalchemy import text

async def fix():
    async with get_db_session() as db:
        # Fix NULL announcement_date for today's records
        r = await db.execute(text(
            "UPDATE quarterly_results qr"
            " SET announcement_date = bal.announcement_date::timestamptz"
            " FROM bse_announcements_log bal"
            " WHERE qr.stock_symbol = bal.scrip_code"
            " AND qr.source_pdf_url = bal.pdf_url"
            " AND qr.announcement_date IS NULL"
            " AND qr.created_at::date = '2026-05-08'"
            " AND bal.announcement_date IS NOT NULL"
            " AND bal.announcement_date != ''"
            " RETURNING qr.id, qr.stock_symbol"
        ))
        fixed = r.fetchall()
        await db.commit()
        print(f"Fixed announcement_date for {len(fixed)} records")
        for row in fixed:
            print(f"  id={row[0]} sym={row[1]}")

        # Check BSE announcements from today with no matching completed extraction
        r3 = await db.execute(text(
            "SELECT bal.scrip_code, bal.company_name, bal.pdf_url, bal.announcement_date"
            " FROM bse_announcements_log bal"
            " WHERE bal.announcement_type = 'result'"
            " AND bal.created_at::date = '2026-05-08'"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM quarterly_results qr"
            "   WHERE qr.stock_symbol = bal.scrip_code"
            "   AND qr.source_pdf_url = bal.pdf_url"
            "   AND qr.extraction_status = 'completed'"
            " )"
            " LIMIT 50"
        ))
        missing = r3.fetchall()
        print(f"\nBSE results with no completed extraction: {len(missing)}")
        for row in missing:
            print(f"  scrip={row[0]} name={row[1]}")

asyncio.run(fix())
