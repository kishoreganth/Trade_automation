"""Tests for stocks endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_stocks(client: AsyncClient):
    resp = await client.get("/api/stocks")
    assert resp.status_code == 200
    data = resp.json()
    assert "stocks" in data


@pytest.mark.asyncio
async def test_get_stock_detail(client: AsyncClient):
    resp = await client.get("/api/stocks/RELIANCE")
    assert resp.status_code == 200
    data = resp.json()
    assert "stock" in data
    assert "quarterly_results" in data


@pytest.mark.asyncio
async def test_refresh_scrip_master(client: AsyncClient):
    resp = await client.post("/api/refresh_scrip_master")
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
