"""Tests for messages endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_messages(client: AsyncClient):
    resp = await client.get("/api/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert "total" in data
    assert "page" in data


@pytest.mark.asyncio
async def test_get_messages_pagination(client: AsyncClient):
    resp = await client.get("/api/messages?page=1&per_page=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["per_page"] == 5


@pytest.mark.asyncio
async def test_get_messages_stats(client: AsyncClient):
    resp = await client.get("/api/messages/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data


@pytest.mark.asyncio
async def test_trigger_message(client: AsyncClient):
    resp = await client.post("/api/trigger_message", json={
        "symbol": "TEST",
        "company_name": "Test Corp",
        "description": "Integration test message",
        "exchange": "NSE"
    })
    assert resp.status_code == 200
