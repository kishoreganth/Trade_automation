"""Tests for configuration endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_scheduled_fetch_config(client: AsyncClient):
    resp = await client.get("/api/config/scheduled_fetch")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "hour" in data


@pytest.mark.asyncio
async def test_get_pe_formulas(client: AsyncClient):
    resp = await client.get("/api/config/pe_formulas")
    assert resp.status_code == 200
    data = resp.json()
    assert "formulas" in data


@pytest.mark.asyncio
async def test_get_sector_formulas(client: AsyncClient):
    resp = await client.get("/api/config/sector_formulas")
    assert resp.status_code == 200
    data = resp.json()
    assert "formulas" in data
