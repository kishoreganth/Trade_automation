"""
FastAPI application entry point.
Production: gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
"""

import asyncio

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .lifespan import lifespan
from .config import get_settings
from .database import engine
from .websocket import ws_manager, websocket_endpoint
from .cache import get_redis
from .routers import messages, pe_analysis, jobs, auth, stocks, config, orders, concall, insights
from .middleware.metrics import router as metrics_router, MetricsMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.logging_mw import RequestLoggingMiddleware, setup_logging
from .middleware.error_handler import register_error_handlers
from .middleware.security import SecurityHeadersMiddleware
from .sentry_setup import init_sentry

settings = get_settings()

# Initialize logging + Sentry before app creation
setup_logging(debug=settings.DEBUG)
init_sentry()

app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)

# Register error handlers
register_error_handlers(app)

# Register routers
app.include_router(auth.router)
app.include_router(messages.router)
app.include_router(pe_analysis.router)
app.include_router(jobs.router)
app.include_router(stocks.router)
app.include_router(config.router)
app.include_router(orders.router)
app.include_router(concall.router)
app.include_router(insights.router)
app.include_router(metrics_router)

# Middleware stack (executed bottom-to-top: CORS → Security → Logging → Metrics → RateLimit)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time", "X-RateLimit-Remaining"],
)


@app.get("/health")
async def health_check():
    """Health check for Docker/Nginx — verifies DB + Redis + WS metrics, all in parallel."""
    async def _check_redis():
        try:
            await get_redis().ping()
            return "ok"
        except Exception:
            return "error"

    async def _check_postgres():
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return "ok"
        except Exception:
            return "error"

    async def _check_ws():
        try:
            return await ws_manager.get_metrics()
        except Exception:
            return {"error": "unavailable"}

    redis_status, pg_status, ws_metrics = await asyncio.gather(
        _check_redis(), _check_postgres(), _check_ws()
    )
    overall = "ok" if redis_status == "ok" and pg_status == "ok" else "degraded"
    payload = {
        "status": overall,
        "postgres": pg_status,
        "redis": redis_status,
        "websocket": ws_metrics,
    }
    if overall != "ok":
        return JSONResponse(content=payload, status_code=503)
    return payload


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket_endpoint(websocket)
