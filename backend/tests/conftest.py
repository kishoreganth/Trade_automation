"""
Pytest fixtures for integration testing.
Uses httpx.AsyncClient with FastAPI's TestClient pattern.
"""

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.cache import get_redis


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    """Authenticated client with valid session token."""
    resp = await client.post("/api/login", json={
        "username": "testuser",
        "password": "testpass123"
    })
    if resp.status_code == 200:
        token = resp.json()["token"]
        client.headers["X-Session-Token"] = token
    yield client


@pytest_asyncio.fixture
async def redis_client():
    """Direct Redis client for cache testing."""
    r = get_redis()
    yield r
    await r.flushdb()
