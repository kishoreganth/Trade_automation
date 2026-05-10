"""Tests for PE analysis endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_pe_analysis(client: AsyncClient):
    resp = await client.get("/api/pe_analysis")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_pe_analysis_with_filters(client: AsyncClient):
    resp = await client.get("/api/pe_analysis?year=2026&quarter=Q4&exchange=NSE")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_pe_filters(client: AsyncClient):
    resp = await client.get("/api/pe_analysis/filters")
    assert resp.status_code == 200
    data = resp.json()
    assert "years" in data
    assert "quarters" in data


@pytest.mark.asyncio
async def test_get_report_summary(client: AsyncClient):
    resp = await client.get("/api/pe_analysis/report_summary")
    assert resp.status_code == 200
