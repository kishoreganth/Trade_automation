"""Tests for health and system endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "postgres" in data
    assert "redis" in data
    assert "websocket" in data


@pytest.mark.asyncio
async def test_health_returns_ws_metrics(client: AsyncClient):
    resp = await client.get("/health")
    data = resp.json()
    ws = data["websocket"]
    if "error" not in ws:
        assert "active_connections" in ws
