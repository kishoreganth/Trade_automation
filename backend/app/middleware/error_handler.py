"""
Global exception handler.
Catches unhandled exceptions, logs them, reports to Sentry, returns clean JSON.
"""

import logging
import traceback
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base application error with status code and user-friendly message."""

    def __init__(self, message: str, status_code: int = 500, detail: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, resource: str, identifier: str = ""):
        super().__init__(
            message=f"{resource} not found" + (f": {identifier}" if identifier else ""),
            status_code=404,
        )


class ConflictError(AppError):
    def __init__(self, message: str = "Resource already exists"):
        super().__init__(message=message, status_code=409)


class RateLimitError(AppError):
    def __init__(self):
        super().__init__(message="Rate limit exceeded", status_code=429)


def _try_capture_sentry(exc: Exception, request: Request):
    """Send exception to Sentry if configured."""
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_extra("path", str(request.url))
            scope.set_extra("method", request.method)
            scope.set_extra("client_ip", request.client.host if request.client else "unknown")
            sentry_sdk.capture_exception(exc)
    except ImportError:
        pass  # Sentry not installed
    except Exception:
        pass  # Sentry reporting failed, don't crash


def register_error_handlers(app: FastAPI):
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail},
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "Validation error",
                "detail": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            f"Unhandled exception [{request_id}]: {type(exc).__name__}: {exc}",
            exc_info=True,
        )
        _try_capture_sentry(exc, request)

        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "request_id": request_id,
            },
        )
