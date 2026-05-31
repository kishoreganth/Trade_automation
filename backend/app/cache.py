"""
Redis client with connection pool, caching helpers, and PubSub support.
Provides: get/set/delete cache, pub/sub for WebSocket fan-out, session store.
"""

import json
import hashlib
import asyncio
from typing import Any, Optional, Callable, Dict
from functools import wraps
import redis.asyncio as redis

from .config import get_settings

settings = get_settings()

# Per-event-loop Redis client (so workers running multiple loops in threads don't share state)
_clients_per_loop: Dict[int, redis.Redis] = {}
_pools_per_loop: Dict[int, redis.ConnectionPool] = {}

# Backwards-compatibility globals (single-loop apps like FastAPI backend keep using these)
_pool: Optional[redis.ConnectionPool] = None
_client: Optional[redis.Redis] = None


def _current_loop_id() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0


async def init_redis() -> redis.Redis:
    """Initialize Redis client for the CURRENT event loop. Safe to call multiple times across loops."""
    global _pool, _client
    loop_id = _current_loop_id()
    if loop_id in _clients_per_loop:
        return _clients_per_loop[loop_id]
    pool = redis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=20,
        decode_responses=True,
    )
    client = redis.Redis(connection_pool=pool)
    await client.ping()
    _clients_per_loop[loop_id] = client
    _pools_per_loop[loop_id] = pool
    if _client is None:
        _client = client
        _pool = pool
    return client


async def close_redis():
    """Close all Redis pools."""
    global _client, _pool
    for client in _clients_per_loop.values():
        try:
            await client.aclose()
        except Exception:
            pass
    for pool in _pools_per_loop.values():
        try:
            await pool.aclose()
        except Exception:
            pass
    _clients_per_loop.clear()
    _pools_per_loop.clear()
    _client = None
    _pool = None


def get_redis() -> redis.Redis:
    """Get the Redis client bound to the CURRENT event loop."""
    loop_id = _current_loop_id()
    client = _clients_per_loop.get(loop_id)
    if client is not None:
        return client
    if _client is not None:
        return _client
    raise RuntimeError("Redis not initialized. Call init_redis() first.")


# ============================================================
# CACHE HELPERS
# ============================================================

CACHE_PREFIX = "trade:"


async def cache_get(key: str) -> Optional[Any]:
    """Get a cached value (auto-deserializes JSON)."""
    r = get_redis()
    raw = await r.get(f"{CACHE_PREFIX}{key}")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


async def cache_set(key: str, value: Any, ttl: int = None):
    """Set a cache value (auto-serializes to JSON). TTL in seconds."""
    r = get_redis()
    ttl = ttl or settings.REDIS_CACHE_TTL
    serialized = json.dumps(value, default=str)
    await r.setex(f"{CACHE_PREFIX}{key}", ttl, serialized)


async def cache_delete(key: str):
    """Delete a single cache key."""
    r = get_redis()
    await r.delete(f"{CACHE_PREFIX}{key}")


async def cache_delete_pattern(pattern: str):
    """Delete all keys matching a pattern (e.g., 'pe_analysis:*')."""
    r = get_redis()
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor, match=f"{CACHE_PREFIX}{pattern}", count=100)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break


def _make_cache_key(prefix: str, args, kwargs) -> str:
    """Generate a deterministic cache key from function arguments."""
    key_data = json.dumps({"a": args, "k": kwargs}, sort_keys=True, default=str)
    key_hash = hashlib.md5(key_data.encode()).hexdigest()[:12]
    return f"{prefix}:{key_hash}"


def cached(prefix: str, ttl: int = None):
    """
    Decorator to cache async function results in Redis.
    
    Usage:
        @cached("pe_analysis_list", ttl=15)
        async def get_pe_analysis(page, filters):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = _make_cache_key(prefix, args, kwargs)
            result = await cache_get(key)
            if result is not None:
                return result
            result = await func(*args, **kwargs)
            if result is not None:
                await cache_set(key, result, ttl)
            return result
        wrapper.cache_prefix = prefix
        return wrapper
    return decorator


# ============================================================
# PUBSUB — WebSocket Fan-out
# ============================================================

WS_CHANNEL = "trade:ws:broadcast"


async def publish_ws_event(event: dict):
    """Publish an event to all WebSocket servers via Redis PubSub."""
    r = get_redis()
    await r.publish(WS_CHANNEL, json.dumps(event, default=str))


async def subscribe_ws_events():
    """
    Subscribe to WebSocket broadcast channel.
    Uses a dedicated connection with no socket timeout so the blocking
    listen() call doesn't raise TimeoutError when idle.
    """
    pool = redis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=2,
        decode_responses=True,
        socket_timeout=None,
        socket_connect_timeout=10,
    )
    client = redis.Redis(connection_pool=pool)
    pubsub = client.pubsub()
    await pubsub.subscribe(WS_CHANNEL)
    return pubsub


# ============================================================
# SESSION STORE
# ============================================================

SESSION_PREFIX = "trade:session:"
SESSION_TTL = 86400  # 24 hours


async def session_set(token: str, user_data: dict, ttl: int = SESSION_TTL):
    """Store session in Redis with auto-expiry."""
    r = get_redis()
    await r.setex(f"{SESSION_PREFIX}{token}", ttl, json.dumps(user_data, default=str))


async def session_get(token: str) -> Optional[dict]:
    """Retrieve session from Redis. Returns None if expired/missing."""
    r = get_redis()
    raw = await r.get(f"{SESSION_PREFIX}{token}")
    if raw is None:
        return None
    return json.loads(raw)


async def session_delete(token: str):
    """Delete session (logout)."""
    r = get_redis()
    await r.delete(f"{SESSION_PREFIX}{token}")


async def session_exists(token: str) -> bool:
    """Check if session is still valid."""
    r = get_redis()
    return await r.exists(f"{SESSION_PREFIX}{token}") > 0
