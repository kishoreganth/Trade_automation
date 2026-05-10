import asyncio
import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_IS_WORKER = bool(os.getenv("CELERY_WORKER")) or "celery" in (os.getenv("_", "") + " " + " ".join(os.sys.argv)).lower()

# ---------------------------------------------------------------------------
# Engine strategy
# ---------------------------------------------------------------------------
# FastAPI: one engine, one pool — the event loop is the same for the process
# lifetime, so a shared pool is safe and fast.
#
# Celery --pool=threads: each thread runs its own event loop via _run_async().
# asyncpg connections are pinned to the loop that created them, so a shared
# pool across threads causes "Future attached to a different loop" crashes.
# Solution: per-loop engine+pool, mirroring the Redis pattern in cache.py.
# ---------------------------------------------------------------------------

_WORKER_POOL_SIZE = 4
_WORKER_MAX_OVERFLOW = 6

_engines_per_loop: dict[int, object] = {}
_sessions_per_loop: dict[int, async_sessionmaker] = {}


def _current_loop_id() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0


def _make_engine():
    """Create a fresh async engine bound to the current event loop."""
    if _IS_WORKER:
        return create_async_engine(
            settings.DATABASE_URL,
            pool_size=_WORKER_POOL_SIZE,
            max_overflow=_WORKER_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=600,
            echo=settings.DEBUG,
        )
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_MIN,
        max_overflow=settings.DB_POOL_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.DEBUG,
    )


if _IS_WORKER:
    engine = None
else:
    engine = _make_engine()


def _get_engine():
    """Return the engine for the current event loop (creates one if needed)."""
    global engine
    if not _IS_WORKER:
        return engine

    loop_id = _current_loop_id()
    eng = _engines_per_loop.get(loop_id)
    if eng is not None:
        return eng

    eng = _make_engine()
    _engines_per_loop[loop_id] = eng
    if engine is None:
        engine = eng
    return eng


def _get_session_factory():
    """Return the session factory for the current event loop."""
    if not _IS_WORKER:
        return AsyncSessionLocal

    loop_id = _current_loop_id()
    factory = _sessions_per_loop.get(loop_id)
    if factory is not None:
        return factory

    factory = async_sessionmaker(
        _get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )
    _sessions_per_loop[loop_id] = factory
    return factory


AsyncSessionLocal = async_sessionmaker(
    engine if engine else _make_engine(),
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session, auto-closes after request."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside of FastAPI routes (background tasks, scripts)."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables if they don't exist (development only — use Alembic in production)."""
    eng = _get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Dispose all engine pools on shutdown."""
    for eng in _engines_per_loop.values():
        try:
            await eng.dispose()
        except Exception:
            pass
    _engines_per_loop.clear()
    _sessions_per_loop.clear()
    if engine is not None:
        await engine.dispose()
