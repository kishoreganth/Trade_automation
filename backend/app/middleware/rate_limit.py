"""
Rate limiting middleware using Redis sliding window.
Per-IP and per-user limits to prevent abuse.
"""

import time
import logging
from typing import Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..cache import get_redis

logger = logging.getLogger(__name__)

# Rate limit configs: (requests, window_seconds)
RATE_LIMITS = {
    "default": (6000, 60),      # 6000 req/min per IP (SPA-friendly with multi-tab + WS invalidation)
    "auth": (20, 60),           # 20 login attempts/min
    "jobs": (60, 60),           # 60 job triggers/min
    "write": (300, 60),         # 300 write ops/min
}

# Read endpoints that are heavily polled by the SPA + already cached server-side.
# Skipping rate limit on these prevents the React-Query/WebSocket fan-out from ever throttling itself.
RATE_LIMIT_EXEMPT_GET = frozenset({
    "/api/messages/stats",
    "/api/messages",
    "/api/pe_analysis",
    "/api/pe_analysis/filters",
    "/api/pe_analysis/report_summary",
    "/api/sectors",
    "/api/stocks",
    "/api/me",
})

RATE_LIMIT_PREFIX = "rl:"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/health", "/ws", "/metrics", "/metrics/json"):
            return await call_next(request)

        # GET reads to heavily-polled cached endpoints bypass the limiter entirely.
        if request.method == "GET" and path in RATE_LIMIT_EXEMPT_GET:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        user_id = request.headers.get("X-Session-Token", client_ip)

        limit_type = self._get_limit_type(request)
        max_requests, window = RATE_LIMITS[limit_type]

        is_allowed = await self._check_rate_limit(
            key=f"{RATE_LIMIT_PREFIX}{limit_type}:{client_ip}",
            max_requests=max_requests,
            window=window,
        )

        if not is_allowed:
            logger.warning(f"Rate limit exceeded: {client_ip} on {request.url.path}")
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(window)},
            )

        response = await call_next(request)

        # Add rate limit headers
        remaining = await self._get_remaining(
            f"{RATE_LIMIT_PREFIX}{limit_type}:{client_ip}", max_requests, window
        )
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Reset"] = str(window)

        return response

    def _get_limit_type(self, request: Request) -> str:
        path = request.url.path
        method = request.method

        if "/login" in path or "/register" in path:
            return "auth"
        if "/jobs" in path and method == "POST":
            return "jobs"
        if method in ("POST", "PUT", "DELETE"):
            return "write"
        return "default"

    async def _check_rate_limit(self, key: str, max_requests: int, window: int) -> bool:
        """Sliding window rate limit check using Redis sorted set."""
        try:
            r = get_redis()
            now = time.time()
            window_start = now - window

            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window + 1)
            results = await pipe.execute()

            current_count = results[2]
            return current_count <= max_requests
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            return True  # Fail open

    async def _get_remaining(self, key: str, max_requests: int, window: int) -> int:
        try:
            r = get_redis()
            now = time.time()
            window_start = now - window
            count = await r.zcount(key, window_start, now)
            return max_requests - count
        except Exception:
            return max_requests
