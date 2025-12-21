import asyncio
import aiohttp
import json
import ssl
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KotakSessionManager:
    """
    Comprehensive session management for Kotak Securities API
    Handles session persistence, validation, and auto-refresh
    """
    
    def __init__(self, session_file: str = "kotak_session.json"):
        self.session_file = Path(session_file)
        self.base_url = "https://gw-napi.kotaksecurities.com"
        self._session_data = None
    
    def _get_next_midnight(self) -> datetime:
        """
        Get the next midnight (12:00 AM) datetime
        
        Returns:
            datetime: Next midnight datetime
        """
        now = datetime.now()
        # Get today's midnight
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # If it's already past midnight today, get tomorrow's midnight
        # This ensures sessions always expire at the next midnight (12:00 AM)
        if now >= today_midnight:
            next_midnight = today_midnight + timedelta(days=1)
        else:
            next_midnight = today_midnight
            
        return next_midnight
        
    async def save_session(self, session_data: Dict[str, Any]) -> bool:
        """
        Save session data to persistent storage with timestamp
        
        Args:
            session_data: Complete session response from final authentication
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            # Extract essential session information
            if "data" in session_data:
                session_info = {
                    "sid": session_data["data"]["sid"],
                    "token": session_data["data"]["token"],
                    "access_token": getattr(self, '_access_token', None),
                    "created_at": datetime.now().isoformat(),
                    "expires_at": self._get_next_midnight().isoformat(),  # Session expires at midnight
                    "full_response": session_data
                }
            else:
                # Handle direct session data format
                session_info = {
                    "sid": session_data.get("sid"),
                    "token": session_data.get("token"),
                    "access_token": getattr(self, '_access_token', None),
                    "created_at": datetime.now().isoformat(),
                    "expires_at": self._get_next_midnight().isoformat(),
                    "full_response": session_data
                }
            
            # Write to file atomically
            temp_file = self.session_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(session_info, f, indent=2)
            
            # Atomic rename
            temp_file.replace(self.session_file)
            
            self._session_data = session_info
            logger.info(f"Session saved successfully to {self.session_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save session: {str(e)}")
            return False
    
    async def load_session(self) -> Optional[Dict[str, Any]]:
        """
        Load session data from persistent storage
        
        Returns:
            Dict containing session data if valid, None otherwise
        """
        try:
            if not self.session_file.exists():
                logger.info("No existing session file found")
                return None
            
            with open(self.session_file, 'r') as f:
                session_data = json.load(f)
            
            # Check if session is expired
            if self._is_session_expired(session_data):
                logger.warning("Loaded session is expired")
                await self.clear_session()
                return None
            
            self._session_data = session_data
            logger.info("Session loaded successfully from storage")
            return session_data
            
        except Exception as e:
            logger.error(f"Failed to load session: {str(e)}")
            return None
    
    def _is_session_expired(self, session_data: Dict[str, Any]) -> bool:
        """Check if the session is expired based on timestamp"""
        try:
            expires_at = datetime.fromisoformat(session_data.get("expires_at", ""))
            return datetime.now() > expires_at
        except Exception:
            logger.warning("Could not determine session expiry, treating as expired")
            return True
    
    async def get_valid_session(self) -> Optional[Dict[str, Any]]:
        """
        Get a valid session, loading from storage or creating new if needed
        
        Returns:
            Dict containing valid session data, None if failed
        """
        # Try to load existing session first
        session_data = await self.load_session()
        
        if session_data and await self.validate_session(session_data):
            logger.info("Using existing valid session")
            return session_data
        
        logger.info("No valid session found, need to authenticate")
        return None
    
    async def validate_session(self, session_data: Dict[str, Any]) -> bool:
        """
        Validate session by making a test API call to portfolio holdings endpoint
        
        Args:
            session_data: Session data to validate
            
        Returns:
            bool: True if session is valid, False otherwise
        """
        try:
            # Create SSL context that allows unverified certificates
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            headers = {
                'accept': '*/*',
                'sid': session_data.get("sid"),
                'Auth': session_data.get("token"),
                'Authorization': f"Bearer {session_data.get('access_token', '')}"
            }
            
            # Use the proven portfolio holdings endpoint for validation
            async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=60, connect=30)) as session:
                async with session.get(
                    f"{self.base_url}/Portfolio/1.0/portfolio/v1/holdings?alt=false",
                    headers=headers
                ) as response:
                    
                    if response.status == 200:
                        logger.info("Session validation successful")
                        return True
                    elif response.status == 401:
                        logger.warning("Session validation failed - unauthorized")
                        await self.clear_session()
                        return False
                    else:
                        logger.warning(f"Session validation uncertain - status: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Session validation error: {str(e)}")
            return False
    
    async def clear_session(self) -> bool:
        """
        Clear session data from storage and memory
        
        Returns:
            bool: True if cleared successfully
        """
        try:
            if self.session_file.exists():
                self.session_file.unlink()
            
            self._session_data = None
            logger.info("Session cleared successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to clear session: {str(e)}")
            return False
    
    async def get_session_headers(self) -> Optional[Dict[str, str]]:
        """
        Get headers for authenticated API calls
        
        Returns:
            Dict containing authentication headers, None if no valid session
        """
        session_data = await self.get_valid_session()
        
        if not session_data:
            return None
        
        return {
            'accept': 'application/json',
            'sid': session_data.get("sid"),
            'Auth': session_data.get("token"),
            'neo-fin-key': 'neotradeapi',
            'Authorization': f"Bearer {session_data.get('access_token', '')}",
            'Content-Type': 'application/json'
        }
    
    def get_session_info(self) -> Optional[Dict[str, Any]]:
        """
        Get current session information
        
        Returns:
            Dict containing session info summary
        """
        if not self._session_data:
            return None
        
        return {
            "sid": self._session_data.get("sid"),
            "created_at": self._session_data.get("created_at"),
            "expires_at": self._session_data.get("expires_at"),
            "is_expired": self._is_session_expired(self._session_data)
        }
    
    def set_access_token(self, access_token: str):
        """Set access token for session management"""
        self._access_token = access_token

# Convenience functions for easy usage
async def get_session_manager() -> KotakSessionManager:
    """Get a configured session manager instance"""
    return KotakSessionManager()

async def save_session_data(session_data: Dict[str, Any]) -> bool:
    """Convenience function to save session data"""
    manager = KotakSessionManager()
    return await manager.save_session(session_data)

async def load_session_data() -> Optional[Dict[str, Any]]:
    """Convenience function to load session data"""
    manager = KotakSessionManager()
    return await manager.load_session()

async def get_auth_headers() -> Optional[Dict[str, str]]:
    """Convenience function to get authentication headers"""
    manager = KotakSessionManager()
    return await manager.get_session_headers()
