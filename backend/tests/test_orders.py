"""Tests for order endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_order_sheet(client: AsyncClient):
    resp = await client.get("/api/place_order/sheet")
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data


@pytest.mark.asyncio
async def test_execute_order_missing_fields(client: AsyncClient):
    resp = await client.post("/api/place_order/execute", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_execute_order_valid(client: AsyncClient):
    resp = await client.post("/api/place_order/execute", json={
        "symbol": "RELIANCE",
        "action": "BUY",
        "qty": 10,
        "price": 2500.0
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "submitted"
