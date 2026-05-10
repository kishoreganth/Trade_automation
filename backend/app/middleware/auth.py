"""
Authentication middleware and dependencies.
Validates session token from X-Session-Token header or cookie.
"""

import logging
from typing import Optional
from fastapi import Request, HTTPException, Depends
from fastapi.security import APIKeyHeader

from ..cache import session_get

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-Session-Token", auto_error=False)

# Public paths that don't require auth
PUBLIC_PATHS = {
    "/health",
    "/api/login",
    "/api/register",
    "/ws",
}


async def get_current_user(token: Optional[str] = Depends(api_key_header)) -> dict:
    """
    FastAPI dependency — validates session token and returns user data.
    Use on endpoints that require authentication.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Session token required")

    user_data = await session_get(token)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return user_data


async def optional_auth(token: Optional[str] = Depends(api_key_header)) -> Optional[dict]:
    """
    FastAPI dependency — returns user data if token valid, None otherwise.
    Use on endpoints that work with or without auth.
    """
    if not token:
        return None

    return await session_get(token)
