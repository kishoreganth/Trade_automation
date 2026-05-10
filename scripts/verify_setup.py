"""
Verification script — checks that all infrastructure is ready.
Run after: docker compose up -d postgres redis

Usage: python scripts/verify_setup.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


async def check_postgres():
    """Verify PostgreSQL is running and schema exists."""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "automation_trade"),
            user=os.getenv("POSTGRES_USER", "trade_user"),
            password=os.getenv("POSTGRES_PASSWORD", "trade_secure_pwd_2026"),
        )
        tables = await conn.fetch("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' ORDER BY table_name
        """)
        await conn.close()

        table_names = [t["table_name"] for t in tables]
        expected = ["messages", "users", "sessions", "stocks", "quarterly_results",
                    "pe_formulas", "sector_formulas", "failed_extractions",
                    "bse_announcements_log", "scheduled_fetch_config"]

        found = [t for t in expected if t in table_names]
        missing = [t for t in expected if t not in table_names]

        print(f"  [{'OK' if not missing else 'WARN'}] PostgreSQL: {len(found)}/{len(expected)} tables")
        if missing:
            print(f"       Missing: {missing}")
            print(f"       Run: docker compose up -d postgres (wait 5s for init_postgres.sql)")
        return not missing
    except Exception as e:
        print(f"  [FAIL] PostgreSQL: {e}")
        print(f"       Run: docker compose up -d postgres")
        return False


async def check_redis():
    """Verify Redis is running."""
    try:
        import redis.asyncio as redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        await r.ping()
        await r.aclose()
        print("  [OK] Redis: connected")
        return True
    except Exception as e:
        print(f"  [FAIL] Redis: {e}")
        print(f"       Run: docker compose up -d redis")
        return False


async def check_backend_imports():
    """Verify all backend modules import without errors."""
    try:
        from app.config import get_settings
        from app.database import Base
        from app.models import Message, QuarterlyResult, Stock
        from app.cache import CACHE_PREFIX
        from app.websocket import ws_manager
        from app.routers import messages, pe_analysis, jobs
        print("  [OK] Backend imports: all modules load")
        return True
    except Exception as e:
        print(f"  [FAIL] Backend imports: {e}")
        return False


async def check_celery_imports():
    """Verify Celery tasks import."""
    try:
        from worker.celery_app import app as celery_app
        from worker.tasks.announcements import fetch_nse_equities
        from worker.tasks.extraction import run_quarterly_extraction
        from worker.tasks.quotes import scheduled_fetch_quotes
        print("  [OK] Celery: all tasks importable")
        return True
    except Exception as e:
        print(f"  [FAIL] Celery imports: {e}")
        return False


async def check_data_migration():
    """Check if data was migrated (messages table has rows)."""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "automation_trade"),
            user=os.getenv("POSTGRES_USER", "trade_user"),
            password=os.getenv("POSTGRES_PASSWORD", "trade_secure_pwd_2026"),
        )
        msg_count = await conn.fetchval("SELECT COUNT(*) FROM messages")
        qr_count = await conn.fetchval("SELECT COUNT(*) FROM quarterly_results")
        stock_count = await conn.fetchval("SELECT COUNT(*) FROM stocks")
        await conn.close()

        if msg_count > 0 or qr_count > 0:
            print(f"  [OK] Data: {msg_count} messages, {qr_count} quarterly_results, {stock_count} stocks")
        else:
            print(f"  [WARN] Data: tables empty — run: python scripts/migrate_sqlite_to_postgres.py")
        return True
    except Exception as e:
        print(f"  [SKIP] Data check: {e}")
        return False


async def main():
    print("=" * 50)
    print("  Automation TRADE — Setup Verification")
    print("=" * 50)
    print()

    results = []

    print("[Infrastructure]")
    results.append(await check_postgres())
    results.append(await check_redis())
    print()

    print("[Backend]")
    results.append(await check_backend_imports())
    results.append(await check_celery_imports())
    print()

    print("[Data]")
    results.append(await check_data_migration())
    print()

    print("=" * 50)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"  ALL CHECKS PASSED ({passed}/{total})")
        print()
        print("  Next steps:")
        print("    1. cd backend && uvicorn app.main:app --port 8000")
        print("    2. cd frontend && npm install && npm run dev")
        print("    3. Open http://localhost:3000")
        print()
        print("  Or full stack:")
        print("    docker compose up -d --build")
    else:
        print(f"  {passed}/{total} PASSED — fix issues above")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
