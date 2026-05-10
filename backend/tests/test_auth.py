"""Tests for authentication endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_missing_fields(client: AsyncClient):
    resp = await client.post("/api/login", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    resp = await client.post("/api/login", json={
        "username": "nonexistent",
        "password": "wrong"
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient):
    resp = await client.post("/api/register", json={
        "username": "testuser",
        "password": "abc"
    })
    assert resp.status_code == 400
    assert "6 characters" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_login_me_flow(client: AsyncClient):
    # Register
    resp = await client.post("/api/register", json={
        "username": "integrationuser",
        "password": "secure123"
    })
    assert resp.status_code in (200, 409)  # 409 if already exists

    # Login
    resp = await client.post("/api/login", json={
        "username": "integrationuser",
        "password": "secure123"
    })
    assert resp.status_code == 200
    token = resp.json()["token"]
    assert token

    # Me
    resp = await client.get("/api/me", headers={"X-Session-Token": token})
    assert resp.status_code == 200
    assert resp.json()["username"] == "integrationuser"
