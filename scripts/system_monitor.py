"""
System Monitor — multi-agent async health monitor for the Automation_TRADE stack.

Monitors:
  1. InfraAgent       — Postgres + Redis connectivity
  2. QueueAgent       — Celery broker queues (io_queue, cpu_queue) + queue/worker mismatch detection
  3. WorkerAgent      — Detect running celery workers via Redis broadcast and terminal logs
  4. DBAgent          — quarterly_results / messages stats (today + lifetime)
  5. ExtractionAgent  — BSE results & board-meeting flow, PDF extraction success rate, stuck rows
  6. APIAgent         — FastAPI /health, WS connection count, rate-limit storm detection
  7. FrontendAgent    — Next.js dev server reachability
  8. ScheduleAgent    — Verify beat schedule matches worker queues

Pure asyncio. No threads. No nested event loops. All agents run concurrently
via asyncio.gather and report into a shared snapshot.

Usage:
  python scripts/system_monitor.py                # one-shot snapshot
  python scripts/system_monitor.py --watch        # continuous, 5s refresh
  python scripts/system_monitor.py --watch -i 10  # custom interval
  python scripts/system_monitor.py --json         # machine-readable output
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import asyncpg  # noqa: E402
import httpx   # noqa: E402
import redis.asyncio as aioredis  # noqa: E402

POSTGRES_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'trade_user')}:"
    f"{os.getenv('POSTGRES_PASSWORD', 'trade_secure_pwd_2026')}@"
    f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
    f"{os.getenv('POSTGRES_PORT', '5432')}/"
    f"{os.getenv('POSTGRES_DB', 'automation_trade')}"
)
REDIS_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
REDIS_CACHE_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
API_BASE = os.getenv("MONITOR_API_BASE", "http://localhost:8000")
FRONTEND_BASE = os.getenv("MONITOR_FRONTEND_BASE", "http://localhost:3000")
TERMINALS_DIR = Path(
    os.getenv(
        "MONITOR_TERMINALS_DIR",
        str(Path.home() / ".cursor/projects/c-Projects-STOCK-HIFI-Project-Market-Automation-TRADE/terminals"),
    )
)

EXPECTED_QUEUES = ("io_queue", "cpu_queue")
LEGACY_QUEUES = ("io_tasks", "cpu_tasks")  # detect old worker invocations
QUEUE_BACKLOG_WARN = 5
QUEUE_BACKLOG_CRIT = 20

RATELIMIT_STORM_WINDOW_S = 30
RATELIMIT_STORM_THRESHOLD = 50

EXTRACTION_STALE_MIN = 30   # warn if no new BSE result in N min during market hours
EXTRACTION_FAIL_RATIO_WARN = 0.5

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"
INFO = "INFO"

ANSI = {
    OK: "\033[32m",      # green
    WARN: "\033[33m",    # yellow
    FAIL: "\033[31m",    # red
    INFO: "\033[36m",    # cyan
    "DIM": "\033[2m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m",
    "CLEAR": "\033[2J\033[H",
}


@dataclass
class AgentReport:
    name: str
    status: str = OK
    summary: str = ""
    details: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0


def _color(level: str, text: str) -> str:
    return f"{ANSI.get(level, '')}{text}{ANSI['RESET']}"


def _badge(level: str) -> str:
    return _color(level, f"[{level:^4}]")


async def _timed(coro):
    t0 = time.perf_counter()
    try:
        result = await coro
    except Exception as e:
        return None, e, (time.perf_counter() - t0) * 1000
    return result, None, (time.perf_counter() - t0) * 1000


# ─────────────── Agents ───────────────

class InfraAgent:
    """Verify Postgres + Redis are reachable."""
    name = "Infra"

    async def run(self) -> AgentReport:
        rep = AgentReport(name=self.name)
        t0 = time.perf_counter()

        pg_ok, pg_err = await self._check_postgres()
        cache_ok, cache_err = await self._check_redis(REDIS_CACHE_URL, "cache")
        broker_ok, broker_err = await self._check_redis(REDIS_BROKER_URL, "broker")

        rep.metrics = {"postgres": pg_ok, "redis_cache": cache_ok, "redis_broker": broker_ok}
        if pg_ok and cache_ok and broker_ok:
            rep.status = OK
            rep.summary = "Postgres + Redis (cache & broker) reachable"
        else:
            rep.status = FAIL
            failures = []
            if not pg_ok: failures.append(f"PG:{pg_err}")
            if not cache_ok: failures.append(f"Redis-cache:{cache_err}")
            if not broker_ok: failures.append(f"Redis-broker:{broker_err}")
            rep.summary = " | ".join(failures)

        rep.elapsed_ms = (time.perf_counter() - t0) * 1000
        return rep

    async def _check_postgres(self):
        try:
            conn = await asyncpg.connect(dsn=POSTGRES_DSN, timeout=3)
            await conn.fetchval("SELECT 1")
            await conn.close()
            return True, None
        except Exception as e:
            return False, str(e)[:80]

    async def _check_redis(self, url, _label):
        try:
            r = aioredis.from_url(url, socket_timeout=3)
            await r.ping()
            await r.aclose()
            return True, None
        except Exception as e:
            return False, str(e)[:80]


class QueueAgent:
    """Inspect Celery broker queues for backlog + queue/worker mismatch."""
    name = "Queue"

    async def run(self) -> AgentReport:
        rep = AgentReport(name=self.name)
        t0 = time.perf_counter()
        try:
            r = aioredis.from_url(REDIS_BROKER_URL, socket_timeout=3, decode_responses=True)
            queue_lens = {}
            for q in EXPECTED_QUEUES + LEGACY_QUEUES:
                queue_lens[q] = int(await r.llen(q))
            unacked = int(await r.hlen("unacked") or 0)
            await r.aclose()
        except Exception as e:
            rep.status = FAIL
            rep.summary = f"broker unreachable: {e}"
            rep.elapsed_ms = (time.perf_counter() - t0) * 1000
            return rep

        rep.metrics = {**queue_lens, "unacked": unacked}

        backlog_total = sum(queue_lens[q] for q in EXPECTED_QUEUES)
        legacy_total = sum(queue_lens[q] for q in LEGACY_QUEUES)

        flags = []
        for q in EXPECTED_QUEUES:
            n = queue_lens[q]
            if n >= QUEUE_BACKLOG_CRIT:
                flags.append(_color(FAIL, f"{q}={n}"))
            elif n >= QUEUE_BACKLOG_WARN:
                flags.append(_color(WARN, f"{q}={n}"))
            else:
                flags.append(_color(OK, f"{q}={n}"))

        rep.details.append("Active queues: " + " ".join(flags))
        rep.details.append(f"Unacked (in-flight) tasks: {unacked}")

        if legacy_total > 0:
            rep.details.append(
                _color(WARN, f"Legacy queues populated: io_tasks={queue_lens['io_tasks']} cpu_tasks={queue_lens['cpu_tasks']}")
                + " (old workers/clients still routing here)"
            )

        if backlog_total >= QUEUE_BACKLOG_CRIT:
            rep.status = FAIL
            rep.summary = f"CRIT backlog={backlog_total} on {EXPECTED_QUEUES} (no consumer?)"
        elif backlog_total >= QUEUE_BACKLOG_WARN:
            rep.status = WARN
            rep.summary = f"backlog={backlog_total} growing"
        else:
            rep.status = OK
            rep.summary = f"queues healthy (backlog={backlog_total})"

        rep.elapsed_ms = (time.perf_counter() - t0) * 1000
        return rep


class WorkerAgent:
    """Detect live Celery workers via control broadcast + identify queue mismatch."""
    name = "Worker"

    async def run(self) -> AgentReport:
        rep = AgentReport(name=self.name)
        t0 = time.perf_counter()

        worker_status = await asyncio.to_thread(self._inspect_workers)
        rep.metrics = worker_status

        active = worker_status.get("active_queues", {})
        if not active:
            rep.status = FAIL
            rep.summary = "no celery workers responded (control broadcast timeout)"
            rep.elapsed_ms = (time.perf_counter() - t0) * 1000
            return rep

        listening_queues = set()
        for _wname, qs in active.items():
            for q in qs:
                listening_queues.add(q.get("name"))

        expected = set(EXPECTED_QUEUES)
        missing = expected - listening_queues
        wrong = listening_queues & set(LEGACY_QUEUES)

        for w, qs in active.items():
            qnames = [q["name"] for q in qs]
            mark = OK if any(q in expected for q in qnames) else WARN
            rep.details.append(_color(mark, f"  worker {w}: queues={qnames}"))

        if missing and wrong:
            rep.status = FAIL
            rep.summary = (
                f"QUEUE MISMATCH — workers on {sorted(wrong)} but tasks routed to "
                f"{sorted(missing)}. Restart workers with -Q {','.join(EXPECTED_QUEUES)}"
            )
        elif missing:
            rep.status = FAIL
            rep.summary = f"no worker for queues: {sorted(missing)}"
        elif wrong:
            rep.status = WARN
            rep.summary = f"legacy queues active: {sorted(wrong)}"
        else:
            rep.status = OK
            rep.summary = f"{len(active)} worker(s) on {sorted(listening_queues)}"

        rep.elapsed_ms = (time.perf_counter() - t0) * 1000
        return rep

    def _inspect_workers(self) -> dict:
        try:
            from celery import Celery
            app = Celery("monitor", broker=REDIS_BROKER_URL)
            insp = app.control.inspect(timeout=2.0)
            active = insp.active_queues() or {}
            stats = insp.stats() or {}
            return {"active_queues": active, "stats": {k: v.get("total", {}) for k, v in stats.items()}}
        except Exception as e:
            return {"error": str(e)[:120], "active_queues": {}}


class DBAgent:
    """Postgres health: row counts, today's activity, schema integrity."""
    name = "Database"

    async def run(self) -> AgentReport:
        rep = AgentReport(name=self.name)
        t0 = time.perf_counter()
        try:
            conn = await asyncpg.connect(dsn=POSTGRES_DSN, timeout=5)
        except Exception as e:
            rep.status = FAIL
            rep.summary = f"connect failed: {e}"
            rep.elapsed_ms = (time.perf_counter() - t0) * 1000
            return rep

        try:
            msg_total = await conn.fetchval("SELECT COUNT(*) FROM messages")
            msg_today = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE timestamp::date = CURRENT_DATE"
            )
            last_msg = await conn.fetchval("SELECT MAX(timestamp) FROM messages")

            qr_total = await conn.fetchval("SELECT COUNT(*) FROM quarterly_results")
            qr_status_rows = await conn.fetch(
                "SELECT extraction_status, COUNT(*) AS n FROM quarterly_results "
                "GROUP BY extraction_status ORDER BY n DESC"
            )
            qr_status = {r["extraction_status"]: int(r["n"]) for r in qr_status_rows}

            qr_today_rows = await conn.fetch(
                "SELECT extraction_status, COUNT(*) AS n FROM quarterly_results "
                "WHERE created_at::date = CURRENT_DATE GROUP BY extraction_status"
            )
            qr_today = {r["extraction_status"]: int(r["n"]) for r in qr_today_rows}

            stuck_pending = await conn.fetchval(
                "SELECT COUNT(*) FROM quarterly_results WHERE extraction_status='pending' "
                "AND created_at < NOW() - INTERVAL '15 minutes'"
            )

            pool_size = await conn.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"
            )
        finally:
            await conn.close()

        rep.metrics = {
            "messages_total": int(msg_total),
            "messages_today": int(msg_today),
            "last_message_iso": last_msg.isoformat() if last_msg else None,
            "qr_total": int(qr_total),
            "qr_status": qr_status,
            "qr_today": qr_today,
            "stuck_pending_15m": int(stuck_pending or 0),
            "pg_connections": int(pool_size),
        }

        rep.details.append(
            f"Messages: total={msg_total:,}  today={msg_today}  "
            f"last={_age(last_msg)}"
        )
        rep.details.append(
            f"QR: total={qr_total:,}  by_status={qr_status}"
        )
        if qr_today:
            rep.details.append(f"QR today: {qr_today}")
        rep.details.append(f"Postgres connections: {pool_size}")

        if stuck_pending and stuck_pending > 0:
            rep.status = WARN
            rep.summary = f"{stuck_pending} extractions pending >15min (workers stuck?)"
        elif msg_today == 0 and _is_market_hours():
            rep.status = WARN
            rep.summary = "no messages today during market hours"
        else:
            rep.status = OK
            rep.summary = f"db healthy — {msg_today} msgs today, {qr_today.get('completed', 0)} extractions completed"

        rep.elapsed_ms = (time.perf_counter() - t0) * 1000
        return rep


class ExtractionAgent:
    """BSE results & board meeting flow. Track new rows, success ratio, latency."""
    name = "Extraction"

    async def run(self) -> AgentReport:
        rep = AgentReport(name=self.name)
        t0 = time.perf_counter()
        try:
            conn = await asyncpg.connect(dsn=POSTGRES_DSN, timeout=5)
        except Exception as e:
            rep.status = FAIL
            rep.summary = f"connect failed: {e}"
            rep.elapsed_ms = (time.perf_counter() - t0) * 1000
            return rep

        try:
            bse_today_rows = await conn.fetch(
                "SELECT extraction_status, COUNT(*) AS n FROM quarterly_results "
                "WHERE exchange='BSE' AND created_at::date = CURRENT_DATE "
                "GROUP BY extraction_status"
            )
            bse_today = {r["extraction_status"]: int(r["n"]) for r in bse_today_rows}

            last_bse = await conn.fetchval(
                "SELECT MAX(created_at) FROM quarterly_results WHERE exchange='BSE'"
            )
            last_bse_completed = await conn.fetchval(
                "SELECT MAX(created_at) FROM quarterly_results "
                "WHERE exchange='BSE' AND extraction_status='completed'"
            )

            recent_failures = await conn.fetch(
                "SELECT stock_symbol, extraction_error, created_at FROM quarterly_results "
                "WHERE created_at::date = CURRENT_DATE AND extraction_status='failed' "
                "ORDER BY created_at DESC LIMIT 5"
            )

            recent_completed = await conn.fetch(
                "SELECT stock_symbol, exchange, financial_year, quarter, created_at "
                "FROM quarterly_results WHERE created_at::date = CURRENT_DATE "
                "AND extraction_status='completed' ORDER BY created_at DESC LIMIT 5"
            )

            board_meeting_msgs = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE option='board_meeting' "
                "AND timestamp::date = CURRENT_DATE"
            )
            result_msgs = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE option IN ('result','quarterly_result') "
                "AND timestamp::date = CURRENT_DATE"
            )
        finally:
            await conn.close()

        completed = bse_today.get("completed", 0)
        failed = bse_today.get("failed", 0)
        pending = bse_today.get("pending", 0)
        total = completed + failed + pending
        fail_ratio = (failed / total) if total else 0.0

        rep.metrics = {
            "bse_today": bse_today,
            "last_bse_iso": last_bse.isoformat() if last_bse else None,
            "last_bse_completed_iso": last_bse_completed.isoformat() if last_bse_completed else None,
            "result_msgs_today": int(result_msgs or 0),
            "board_meeting_msgs_today": int(board_meeting_msgs or 0),
            "fail_ratio": round(fail_ratio, 2),
            "recent_failures": [
                {"symbol": r["stock_symbol"], "error": (r["extraction_error"] or "")[:100],
                 "at": r["created_at"].isoformat()} for r in recent_failures
            ],
            "recent_completed": [
                {"symbol": r["stock_symbol"], "exch": r["exchange"],
                 "fy": r["financial_year"], "q": r["quarter"],
                 "at": r["created_at"].isoformat()} for r in recent_completed
            ],
        }

        rep.details.append(
            f"BSE today: {bse_today or '{}'}  fail_ratio={fail_ratio:.0%}"
        )
        rep.details.append(
            f"Messages today: result={result_msgs}  board_meeting={board_meeting_msgs}"
        )
        rep.details.append(
            f"Last BSE row: {_age(last_bse)}  | last completed: {_age(last_bse_completed)}"
        )
        if recent_failures:
            rep.details.append(_color(WARN, "Recent failures:"))
            for r in recent_failures[:3]:
                rep.details.append(
                    f"  - {r['stock_symbol']}: {(r['extraction_error'] or '')[:80]}"
                )
        if recent_completed:
            rep.details.append("Recent completed:")
            for r in recent_completed[:3]:
                rep.details.append(
                    f"  - {r['stock_symbol']} {r['exchange']} {r['financial_year']}/{r['quarter']}"
                )

        if total == 0 and _is_market_hours():
            rep.status = WARN
            rep.summary = "no BSE extractions today during market hours"
        elif fail_ratio >= EXTRACTION_FAIL_RATIO_WARN and total >= 5:
            rep.status = WARN
            rep.summary = f"high failure ratio {fail_ratio:.0%} ({failed}/{total})"
        elif pending > 10:
            rep.status = WARN
            rep.summary = f"{pending} extractions pending"
        else:
            rep.status = OK
            rep.summary = f"flow healthy — {completed} ok / {failed} failed / {pending} pending today"

        rep.elapsed_ms = (time.perf_counter() - t0) * 1000
        return rep


class APIAgent:
    """FastAPI /health, WebSocket connection count, rate-limit storm detection."""
    name = "API"

    async def run(self) -> AgentReport:
        rep = AgentReport(name=self.name)
        t0 = time.perf_counter()

        async with httpx.AsyncClient(timeout=4.0) as client:
            health, h_err, h_ms = await _timed(client.get(f"{API_BASE}/health"))

        if health is None or health.status_code != 200:
            rep.status = FAIL
            rep.summary = f"/health unreachable: {h_err or health.status_code}"
            rep.elapsed_ms = (time.perf_counter() - t0) * 1000
            return rep

        try:
            payload = health.json()
        except Exception:
            payload = {}

        ws_metrics = payload.get("websocket", {})
        rep.metrics = {
            "health_payload": payload,
            "health_latency_ms": round(h_ms, 1),
        }
        rep.details.append(
            f"/health: status={payload.get('status')} pg={payload.get('postgres')} "
            f"redis={payload.get('redis')} latency={h_ms:.0f}ms"
        )
        if ws_metrics:
            rep.details.append(
                f"WS: local={ws_metrics.get('local_connections', '?')} "
                f"total={ws_metrics.get('total_connections', '?')} "
                f"unique_ips={ws_metrics.get('unique_ips', '?')}"
            )

        storm = await self._detect_ratelimit_storm()
        rep.metrics["ratelimit_storm"] = storm
        if storm["count"] > 0:
            rep.details.append(
                _color(WARN if storm['count'] < RATELIMIT_STORM_THRESHOLD else FAIL,
                       f"Rate-limit hits last {RATELIMIT_STORM_WINDOW_S}s: {storm['count']} "
                       f"on {storm['paths']}")
            )

        if any(payload.get(k) not in ("ok", None) for k in ("status", "postgres", "redis")):
            rep.status = WARN
            rep.summary = "API up but a dependency reports unhealthy"
        elif storm["count"] >= RATELIMIT_STORM_THRESHOLD:
            rep.status = WARN
            rep.summary = f"rate-limit storm ({storm['count']} 429s/{RATELIMIT_STORM_WINDOW_S}s)"
        else:
            rep.status = OK
            rep.summary = f"API healthy ({h_ms:.0f}ms)"

        rep.elapsed_ms = (time.perf_counter() - t0) * 1000
        return rep

    async def _detect_ratelimit_storm(self) -> dict:
        """Scan latest API terminal log for recent 429 responses."""
        if not TERMINALS_DIR.exists():
            return {"count": 0, "paths": [], "source": "no terminals dir"}
        try:
            files = sorted(TERMINALS_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            cutoff = datetime.now() - timedelta(seconds=RATELIMIT_STORM_WINDOW_S)
            count = 0
            path_counts: dict[str, int] = {}
            for fp in files[:5]:
                try:
                    raw = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "Rate limit exceeded" not in raw:
                    continue
                tail = "\n".join(raw.splitlines()[-400:])
                for line in tail.splitlines():
                    if "Rate limit exceeded" not in line:
                        continue
                    ts = _parse_log_ts(line)
                    if ts and ts >= cutoff:
                        count += 1
                        for p in ("/api/messages/stats", "/api/messages",
                                  "/api/pe_analysis", "/api/pe_analysis/filters"):
                            if p in line:
                                path_counts[p] = path_counts.get(p, 0) + 1
                                break
            return {"count": count, "paths": list(path_counts.keys())}
        except Exception as e:
            return {"count": 0, "paths": [], "error": str(e)[:80]}


class FrontendAgent:
    """Verify Next.js dev server is reachable and serving."""
    name = "Frontend"

    async def run(self) -> AgentReport:
        rep = AgentReport(name=self.name)
        t0 = time.perf_counter()

        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
            res, err, ms = await _timed(client.get(f"{FRONTEND_BASE}/"))

        if res is None:
            rep.status = FAIL
            rep.summary = f"frontend unreachable: {err}"
            rep.elapsed_ms = (time.perf_counter() - t0) * 1000
            return rep

        rep.metrics = {"status_code": res.status_code, "latency_ms": round(ms, 1)}
        rep.details.append(f"GET {FRONTEND_BASE}/ -> {res.status_code} ({ms:.0f}ms)")

        body_signal = "next" in res.text.lower() or "_next" in res.text.lower()
        rep.metrics["next_markup"] = body_signal

        if res.status_code != 200:
            rep.status = WARN
            rep.summary = f"non-200 {res.status_code}"
        elif not body_signal:
            rep.status = WARN
            rep.summary = "200 OK but Next.js markup not detected"
        else:
            rep.status = OK
            rep.summary = f"frontend up ({ms:.0f}ms)"

        rep.elapsed_ms = (time.perf_counter() - t0) * 1000
        return rep


class ScheduleAgent:
    """Confirm beat schedule routes match worker queue listening."""
    name = "Schedule"

    async def run(self) -> AgentReport:
        rep = AgentReport(name=self.name)
        t0 = time.perf_counter()

        beat_file = PROJECT_ROOT / "backend" / "worker" / "beat_schedule.py"
        if not beat_file.exists():
            rep.status = WARN
            rep.summary = "beat_schedule.py not found"
            rep.elapsed_ms = (time.perf_counter() - t0) * 1000
            return rep

        try:
            text = await asyncio.to_thread(beat_file.read_text, "utf-8")
        except Exception as e:
            rep.status = FAIL
            rep.summary = f"read beat_schedule failed: {e}"
            rep.elapsed_ms = (time.perf_counter() - t0) * 1000
            return rep

        routed = set()
        for q in EXPECTED_QUEUES + LEGACY_QUEUES:
            if f'"queue": "{q}"' in text or f"'queue': '{q}'" in text:
                routed.add(q)

        rep.metrics = {"routed_queues": sorted(routed)}
        rep.details.append(f"Beat routes tasks to: {sorted(routed)}")

        legacy_used = routed & set(LEGACY_QUEUES)
        if legacy_used:
            rep.status = FAIL
            rep.summary = f"beat still routes to legacy queues: {sorted(legacy_used)}"
        elif not routed:
            rep.status = WARN
            rep.summary = "no queue routing detected in beat_schedule.py"
        else:
            rep.status = OK
            rep.summary = f"beat routing OK ({sorted(routed)})"

        rep.elapsed_ms = (time.perf_counter() - t0) * 1000
        return rep


# ─────────────── Helpers ───────────────

def _is_market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    return (h == 9 and m >= 15) or (10 <= h < 15) or (h == 15 and m <= 30)


def _age(ts: datetime | None) -> str:
    if ts is None:
        return _color(WARN, "never")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    s = int(delta.total_seconds())
    if s < 60:
        return _color(OK, f"{s}s ago")
    if s < 3600:
        m = s // 60
        return _color(OK if m < 5 else WARN, f"{m}m ago")
    if s < 86400:
        return _color(WARN, f"{s // 3600}h ago")
    return _color(WARN, f"{s // 86400}d ago")


def _parse_log_ts(line: str) -> datetime | None:
    """Extract ISO-style timestamp prefix from JSON-formatted log lines."""
    idx = line.find('"timestamp": "')
    if idx == -1:
        return None
    end = line.find('"', idx + 14)
    if end == -1:
        return None
    raw = line[idx + 14:end]
    for fmt in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


# ─────────────── Coordinator ───────────────

AGENTS: tuple = (
    InfraAgent(),
    QueueAgent(),
    WorkerAgent(),
    ScheduleAgent(),
    DBAgent(),
    ExtractionAgent(),
    APIAgent(),
    FrontendAgent(),
)


async def collect_snapshot() -> list[AgentReport]:
    return await asyncio.gather(*(a.run() for a in AGENTS))


def _format_snapshot(reports: list[AgentReport]) -> str:
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    counts = {OK: 0, WARN: 0, FAIL: 0}
    for r in reports:
        counts[r.status] = counts.get(r.status, 0) + 1

    header = (
        f"{ANSI['BOLD']}Automation_TRADE — System Monitor{ANSI['RESET']}  "
        f"{ANSI['DIM']}{now}{ANSI['RESET']}  "
        f"[{_color(OK, str(counts[OK]) + ' OK')}  "
        f"{_color(WARN, str(counts[WARN]) + ' WARN')}  "
        f"{_color(FAIL, str(counts[FAIL]) + ' FAIL')}]"
    )
    lines.append(header)
    lines.append(ANSI['DIM'] + "-" * 100 + ANSI['RESET'])

    for r in reports:
        lines.append(f"{_badge(r.status)} {r.name:<10} {r.summary}  "
                     f"{ANSI['DIM']}({r.elapsed_ms:.0f}ms){ANSI['RESET']}")
        for d in r.details:
            lines.append(f"          {ANSI['DIM']}|{ANSI['RESET']} {d}")
    lines.append(ANSI['DIM'] + "-" * 100 + ANSI['RESET'])
    return "\n".join(lines)


def _serialize(reports: list[AgentReport]) -> str:
    return json.dumps([asdict(r) for r in reports], default=str, indent=2)


async def watch_loop(interval: float, as_json: bool) -> None:
    history: deque = deque(maxlen=20)
    while True:
        reports = await collect_snapshot()
        history.append({"ts": datetime.now().isoformat(), "reports": reports})
        if as_json:
            print(_serialize(reports), flush=True)
        else:
            print(ANSI["CLEAR"] + _format_snapshot(reports), flush=True)
            print(f"{ANSI['DIM']}Refresh every {interval:.0f}s — Ctrl+C to exit{ANSI['RESET']}",
                  flush=True)
        await asyncio.sleep(interval)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", action="store_true", help="continuous monitoring loop")
    parser.add_argument("-i", "--interval", type=float, default=5.0, help="refresh interval seconds (watch mode)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of formatted text")
    args = parser.parse_args()

    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
        except Exception:
            for k in list(ANSI.keys()):
                ANSI[k] = ""

    if args.watch:
        try:
            await watch_loop(args.interval, args.json)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\nMonitor stopped.")
        return 0

    reports = await collect_snapshot()
    if args.json:
        print(_serialize(reports))
    else:
        print(_format_snapshot(reports))

    if any(r.status == FAIL for r in reports):
        return 2
    if any(r.status == WARN for r in reports):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
