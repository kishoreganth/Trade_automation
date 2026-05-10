"""Re-trigger failed extractions from today using the fixed code."""
import asyncio, os, sys
from datetime import date

sys.path.insert(0, 'backend')
os.environ.setdefault('ENV_FILE', '.env')
os.environ.setdefault('CELERY_BROKER_URL', 'redis://localhost:6379/1')
os.environ.setdefault('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')

from app.database import get_db_session
from sqlalchemy import text
from worker.celery_app import app


async def retrigger():
    async with get_db_session() as db:
        r = await db.execute(text(
            "SELECT DISTINCT bal.scrip_code, bal.company_name, bal.pdf_url, bal.announcement_date "
            "FROM bse_announcements_log bal "
            "WHERE bal.announcement_type = 'result' "
            "AND bal.created_at >= NOW() - INTERVAL '36 hours' "
            "AND NOT EXISTS ("
            "   SELECT 1 FROM quarterly_results qr "
            "   WHERE qr.stock_symbol = bal.scrip_code "
            "   AND qr.source_pdf_url = bal.pdf_url "
            "   AND qr.extraction_status = 'completed' "
            "   AND COALESCE(qr.eps_basic_standalone, qr.eps_diluted_standalone, "
            "                qr.eps_basic_consolidated, qr.eps_diluted_consolidated) IS NOT NULL"
            ")"
        ))
        missing = r.fetchall()
        print(f"Re-triggering {len(missing)} extractions (last 36h)...")

        for row in missing:
            scrip, name, pdf, ann_date = row
            print(f"  Queuing: {scrip} ({name})")
            app.send_task(
                "worker.tasks.extraction.run_quarterly_extraction",
                kwargs={
                    "stock_symbol": scrip,
                    "pdf_url": pdf,
                    "exchange": "BSE",
                    "company_name": name or "",
                    "announcement_date": ann_date,
                },
                queue="cpu_queue",
            )

        print(f"\nQueued {len(missing)} extractions to cpu_queue")


asyncio.run(retrigger())
