"""Tests for jobs endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_start_job_invalid_type(client: AsyncClient):
    resp = await client.post("/api/jobs/invalid_type/start")
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_start_fetch_nse_job(client: AsyncClient):
    resp = await client.post("/api/jobs/fetch_nse/start")
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data or "success" in data


@pytest.mark.asyncio
async def test_start_ai_analysis(client: AsyncClient):
    resp = await client.post("/api/jobs/ai_analysis/start", json={
        "symbol": "RELIANCE"
    })
    assert resp.status_code == 200
