"""
Prometheus-compatible metrics endpoint.
Exposes request counts, latencies, and system metrics.
"""

import time
import asyncio
from collections import defaultdict
from typing import Dict

from fastapi import APIRouter, Request
from starlette.middleware.base import BaseHTTPMiddleware

router = APIRouter(tags=["metrics"])

# In-memory metrics (for single-instance; use prometheus_client for multi-instance)
_metrics: Dict[str, any] = {
    "requests_total": defaultdict(int),
    "requests_duration_ms": defaultdict(list),
    "requests_errors": defaultdict(int),
    "active_requests": 0,
}
_start_time = time.time()


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collects request metrics."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        path = self._normalize_path(request.url.path)
        method = request.method
        key = f"{method}:{path}"

        _metrics["active_requests"] += 1
        start = time.perf_counter()

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000

            _metrics["requests_total"][key] += 1
            _metrics["requests_duration_ms"][key].append(duration_ms)

            # Keep only last 1000 durations per endpoint
            if len(_metrics["requests_duration_ms"][key]) > 1000:
                _metrics["requests_duration_ms"][key] = _metrics["requests_duration_ms"][key][-500:]

            if response.status_code >= 500:
                _metrics["requests_errors"][key] += 1

            return response
        except Exception:
            _metrics["requests_errors"][key] += 1
            raise
        finally:
            _metrics["active_requests"] -= 1

    def _normalize_path(self, path: str) -> str:
        """Normalize paths to avoid cardinality explosion."""
        parts = path.split("/")
        normalized = []
        for part in parts:
            if part and (part.isdigit() or len(part) > 20):
                normalized.append("{id}")
            else:
                normalized.append(part)
        return "/".join(normalized)


@router.get("/metrics")
async def get_metrics():
    """Prometheus-style metrics endpoint."""
    uptime = time.time() - _start_time

    lines = []
    lines.append(f"# HELP uptime_seconds Application uptime")
    lines.append(f"uptime_seconds {uptime:.0f}")
    lines.append(f"# HELP active_requests Current active requests")
    lines.append(f"active_requests {_metrics['active_requests']}")

    lines.append(f"# HELP requests_total Total request count by endpoint")
    for key, count in sorted(_metrics["requests_total"].items()):
        method, path = key.split(":", 1)
        lines.append(f'requests_total{{method="{method}",path="{path}"}} {count}')

    lines.append(f"# HELP requests_errors Total error count by endpoint")
    for key, count in sorted(_metrics["requests_errors"].items()):
        method, path = key.split(":", 1)
        lines.append(f'requests_errors{{method="{method}",path="{path}"}} {count}')

    lines.append(f"# HELP request_duration_ms_avg Average request duration")
    for key, durations in sorted(_metrics["requests_duration_ms"].items()):
        if durations:
            method, path = key.split(":", 1)
            avg = sum(durations) / len(durations)
            p95 = sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 1 else durations[0]
            lines.append(f'request_duration_ms_avg{{method="{method}",path="{path}"}} {avg:.1f}')
            lines.append(f'request_duration_ms_p95{{method="{method}",path="{path}"}} {p95:.1f}')

    return "\n".join(lines)


@router.get("/metrics/json")
async def get_metrics_json():
    """JSON format metrics for dashboards."""
    uptime = time.time() - _start_time

    endpoints = {}
    for key, count in _metrics["requests_total"].items():
        durations = _metrics["requests_duration_ms"].get(key, [])
        errors = _metrics["requests_errors"].get(key, 0)
        endpoints[key] = {
            "total": count,
            "errors": errors,
            "avg_ms": round(sum(durations) / len(durations), 1) if durations else 0,
            "p95_ms": round(sorted(durations)[int(len(durations) * 0.95)], 1) if len(durations) > 1 else 0,
        }

    return {
        "uptime_seconds": round(uptime),
        "active_requests": _metrics["active_requests"],
        "endpoints": endpoints,
    }
