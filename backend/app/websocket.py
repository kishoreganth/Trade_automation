"""
WebSocket manager with Redis PubSub fan-out — production-grade for 1000+ concurrent connections.
Features: Redis connection tracking, per-IP limits, dead client cleanup, metrics.
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect

from .cache import publish_ws_event, subscribe_ws_events, get_redis

logger = logging.getLogger(__name__)

MAX_CONNECTIONS_PER_IP = 5
HEARTBEAT_TIMEOUT_S = 45
METRICS_KEY = "trade:ws:metrics"
CONNECTIONS_KEY = "trade:ws:connections"


class WebSocketManager:
    """
    Production WebSocket manager with:
    - Redis PubSub for cross-worker broadcasting
    - Per-IP connection limiting
    - Dead client detection via heartbeat tracking
    - Connection metrics exposed for monitoring
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._ip_connections: Dict[str, int] = {}
        self._last_pong: Dict[WebSocket, float] = {}
        self._pubsub_task: asyncio.Task = None
        self._cleanup_task: asyncio.Task = None

    async def start(self):
        """Start PubSub listener and dead client cleanup loop."""
        self._pubsub_task = asyncio.create_task(self._listen_redis())
        self._cleanup_task = asyncio.create_task(self._cleanup_dead_clients())
        logger.info("WebSocket manager started (PubSub + cleanup)")

    async def stop(self):
        """Graceful shutdown — close all connections, stop tasks."""
        for task in [self._pubsub_task, self._cleanup_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        for conn in list(self.active_connections):
            try:
                await conn.close(code=1001, reason="Server shutting down")
            except Exception:
                pass
        self.active_connections.clear()
        self._ip_connections.clear()
        self._last_pong.clear()

        try:
            r = get_redis()
            await r.delete(CONNECTIONS_KEY)
        except Exception:
            pass

        logger.info("WebSocket manager stopped")

    def _get_client_ip(self, websocket: WebSocket) -> str:
        """Extract client IP (supports X-Forwarded-For from Nginx)."""
        forwarded = websocket.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = websocket.client
        return client.host if client else "unknown"

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept connection if under per-IP limit. Returns False if rejected."""
        ip = self._get_client_ip(websocket)

        if self._ip_connections.get(ip, 0) >= MAX_CONNECTIONS_PER_IP:
            logger.warning(f"WS rejected: {ip} at limit ({MAX_CONNECTIONS_PER_IP})")
            await websocket.close(code=1008, reason="Too many connections")
            return False

        await websocket.accept()
        self.active_connections.append(websocket)
        self._ip_connections[ip] = self._ip_connections.get(ip, 0) + 1
        self._last_pong[websocket] = time.time()

        await self._update_connection_count(1)
        logger.info(f"WS connected: {ip} (total: {len(self.active_connections)})")
        return True

    def disconnect(self, websocket: WebSocket):
        """Remove connection and update tracking."""
        if websocket not in self.active_connections:
            return

        ip = self._get_client_ip(websocket)
        self.active_connections.remove(websocket)
        self._last_pong.pop(websocket, None)

        if ip in self._ip_connections:
            self._ip_connections[ip] = max(0, self._ip_connections[ip] - 1)
            if self._ip_connections[ip] == 0:
                del self._ip_connections[ip]

        asyncio.create_task(self._update_connection_count(-1))
        logger.info(f"WS disconnected: {ip} (total: {len(self.active_connections)})")

    def record_pong(self, websocket: WebSocket):
        """Record that client responded to ping (alive)."""
        self._last_pong[websocket] = time.time()

    async def broadcast_local(self, message: dict):
        """Broadcast to all connections on THIS worker."""
        if not self.active_connections:
            return
        disconnected = []
        payload = json.dumps(message, default=str)
        for conn in self.active_connections:
            try:
                await conn.send_text(payload)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast(self, message: dict):
        """Publish to Redis PubSub — reaches ALL workers' connections."""
        await publish_ws_event(message)

    async def get_metrics(self) -> dict:
        """Get WebSocket metrics for health endpoint."""
        try:
            r = get_redis()
            total = await r.get(CONNECTIONS_KEY)
        except Exception:
            total = None

        return {
            "local_connections": len(self.active_connections),
            "total_connections": int(total) if total else len(self.active_connections),
            "unique_ips": len(self._ip_connections),
        }

    # ─── Internal ───

    async def _update_connection_count(self, delta: int):
        """Atomically update global connection count in Redis."""
        try:
            r = get_redis()
            if delta > 0:
                await r.incr(CONNECTIONS_KEY)
            else:
                val = await r.decr(CONNECTIONS_KEY)
                if val < 0:
                    await r.set(CONNECTIONS_KEY, 0)
        except Exception:
            pass

    async def _cleanup_dead_clients(self):
        """Periodic task: close connections that haven't responded to ping in 45s."""
        while True:
            try:
                await asyncio.sleep(30)
                now = time.time()
                dead = [
                    ws for ws, last in self._last_pong.items()
                    if now - last > HEARTBEAT_TIMEOUT_S
                ]
                for ws in dead:
                    logger.info(f"Closing dead WS (no pong in {HEARTBEAT_TIMEOUT_S}s)")
                    self.disconnect(ws)
                    try:
                        await ws.close(code=1001, reason="Heartbeat timeout")
                    except Exception:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
                await asyncio.sleep(5)

    async def _listen_redis(self):
        """Subscribe to Redis PubSub and forward events to local connections."""
        pubsub = None
        while True:
            try:
                if pubsub:
                    try:
                        await pubsub.unsubscribe()
                        await pubsub.aclose()
                    except Exception:
                        pass
                    pubsub = None
                pubsub = await subscribe_ws_events()
                async for raw_msg in pubsub.listen():
                    if raw_msg["type"] != "message":
                        continue
                    try:
                        event = json.loads(raw_msg["data"])
                        await self.broadcast_local(event)
                    except (json.JSONDecodeError, TypeError):
                        continue
            except asyncio.CancelledError:
                if pubsub:
                    try:
                        await pubsub.unsubscribe()
                        await pubsub.aclose()
                    except Exception:
                        pass
                break
            except Exception as e:
                logger.error(f"PubSub listener error: {e}")
                await asyncio.sleep(5)


# Singleton
ws_manager = WebSocketManager()


async def websocket_endpoint(websocket: WebSocket):
    """FastAPI WebSocket endpoint — ping/pong keepalive + per-IP limiting."""
    accepted = await ws_manager.connect(websocket)
    if not accepted:
        return

    try:
        await websocket.send_json({"type": "connected"})
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                ws_manager.record_pong(websocket)
                await websocket.send_text("pong")
    except (WebSocketDisconnect, Exception):
        ws_manager.disconnect(websocket)
