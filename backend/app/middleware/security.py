"""
Security middleware — adds hardened HTTP headers, XSS/clickjacking protection,
and an X-App-Version header so the frontend can detect backend redeployments.
"""

import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

BUILD_VERSION = os.environ.get("BUILD_VERSION", "dev")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers + app version to all responses."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-App-Version"] = BUILD_VERSION

        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy (disable unnecessary browser features)
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )

        # Strict Transport Security (for HTTPS)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

        # Content Security Policy (API — no HTML rendering needed)
        if "/api/" in request.url.path or request.url.path == "/health":
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"

        return response
