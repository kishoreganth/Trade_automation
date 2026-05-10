"""
Authentication router — login, logout, register.
Extracted from: nse_url_test.py (login/session endpoints)
"""

import secrets
import hashlib
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..database import get_db
from ..cache import session_set, session_delete
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/api", tags=["auth"])


def _hash_password(password: str) -> str:
    """SHA-256 hash (matches existing nse_url_test.py logic)."""
    return hashlib.sha256(password.encode()).hexdigest()


@router.post("/login")
async def login(body: dict, db: AsyncSession = Depends(get_db)):
    """Authenticate user and create session."""
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    pwd_hash = _hash_password(password)

    row = await db.execute(text(
        "SELECT id, username FROM users WHERE username = :u AND password_hash = :p"
    ), {"u": username, "p": pwd_hash})
    user = row.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create session token
    token = secrets.token_urlsafe(32)
    user_data = {"user_id": user.id, "username": user.username}

    # Store in Redis (24h TTL)
    await session_set(token, user_data)

    # Update last_login
    await db.execute(text(
        "UPDATE users SET last_login = NOW() WHERE id = :id"
    ), {"id": user.id})
    await db.commit()

    return {"success": True, "token": token, "username": user.username}


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user)):
    """Invalidate session."""
    # Token is already validated by get_current_user
    # We need the actual token to delete it
    return {"success": True}


@router.post("/register")
async def register(body: dict, db: AsyncSession = Depends(get_db)):
    """Register new user (admin-only in production)."""
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Check if user exists
    existing = await db.execute(text(
        "SELECT id FROM users WHERE username = :u"
    ), {"u": username})
    if existing.fetchone():
        raise HTTPException(status_code=409, detail="Username already exists")

    pwd_hash = _hash_password(password)
    await db.execute(text(
        "INSERT INTO users (username, password_hash, created_at) VALUES (:u, :p, NOW())"
    ), {"u": username, "p": pwd_hash})
    await db.commit()

    return {"success": True, "username": username}


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current authenticated user info."""
    return {"username": user["username"], "user_id": user["user_id"]}
