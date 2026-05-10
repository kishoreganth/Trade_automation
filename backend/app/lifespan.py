"""
FastAPI lifespan: startup/shutdown for database pool, Redis, and WebSocket PubSub.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

from .database import init_db, close_db
from .cache import init_redis, close_redis
from .websocket import ws_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the application."""
    # Startup
    logger.info("Starting up...")
    await init_redis()
    logger.info("Redis connected")
    
    await ws_manager.start()
    logger.info("WebSocket PubSub listener started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await ws_manager.stop()
    await close_redis()
    await close_db()
    logger.info("All connections closed")
