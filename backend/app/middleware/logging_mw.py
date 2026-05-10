"""
Structured JSON logging middleware + request tracking.
Outputs structured logs for aggregation (ELK/Loki/CloudWatch).
"""

import time
import logging
import json
import sys
import uuid
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


def setup_logging(debug: bool = False):
    """Configure structured logging for the application."""
    level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    # Quiet noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request with timing, status, and correlation ID."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        path = request.url.path

        # Suppress noisy / high-frequency log lines:
        #   - /health: pinged by docker, monitor, k8s every few seconds
        #   - /metrics, /metrics/json: scraped frequently
        #   - 200 OK on heavily-cached read endpoints (only log non-2xx)
        if path in ("/health", "/metrics", "/metrics/json"):
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
            return response

        # Only log read endpoints when status >= 400 (errors / rate limits).
        is_cached_read = (
            request.method == "GET"
            and path in (
                "/api/messages",
                "/api/messages/stats",
                "/api/pe_analysis",
                "/api/pe_analysis/filters",
                "/api/pe_analysis/report_summary",
                "/api/sectors",
            )
        )
        if not (is_cached_read and response.status_code < 400):
            logger = logging.getLogger("api.access")
            logger.info(
                f"{request.method} {path} → {response.status_code} ({duration_ms:.1f}ms)",
                extra={"request_id": request_id},
            )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
        return response
