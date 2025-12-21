import asyncio
import aiohttp
import json
import ssl
from typing import Optional, Dict, Any
import logging
from dotenv import load_dotenv

load_dotenv()


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KotakFinalSessionClient:
    """Async client for final session validation with MPIN in Kotak Securities"""
    
    def __init__(self):
        self.base_url = "https://gw-napi.kotaksecurities.com"
        
    async def validate_final_session(
        self, 
        access_token: str, 
        sid: str, 
        jwt_auth_token: str, 
        mpin: str
    ) -> Optional[Dict[str, Any]]:
        """
        Validate final session with MPIN to complete Kotak Securities authentication
        
        Args:
            access_token: Bearer token from access token API
            sid: Session ID from TOTP login response
            jwt_auth_token: JWT token from TOTP login response
            mpin: Mobile PIN for final authentication
            
        Returns:
            Dict containing final session response data, or None if failed
        """
        # Create SSL context that allows unverified certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        payload = {
            "mpin": mpin
        }
        
        headers = {
            'accept': 'application/json',
            'sid': sid,
            'Auth': jwt_auth_token,
            'neo-fin-key': 'neotradeapi',
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {access_token}"
        }
        
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=120, connect=60)) as session:
                async with session.post(
                    f"{self.base_url}/login/1.0/login/v6/totp/validate",
                    json=payload,
                    headers=headers
                ) as response:
                    
                    response_text = await response.text()
                    
                    if response.status == 200:
                        logger.info(f"Successfully validated final session with MPIN")
                        
                        try:
                            session_data = json.loads(response_text)
                            return session_data
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse JSON response: {response_text}")
                            return None
                    else:
                        logger.error(f"Final session validation failed. Status: {response.status}, Response: {response_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("Request timed out while validating final session")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during final session validation: {str(e)}")
            return None

# Convenience function for standalone usage
async def validate_final_session(access_token: str, sid: str, jwt_auth_token: str, mpin: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to validate final session with MPIN
    
    Args:
        access_token: Bearer token from access token API
        sid: Session ID from TOTP login response
        jwt_auth_token: JWT token from TOTP login response
        mpin: Mobile PIN for final authentication
        
    Returns:
        Dict containing final session response data, or None if failed
    """
    client = KotakFinalSessionClient()
    return await client.validate_final_session(access_token, sid, jwt_auth_token, mpin)

# Main async function for standalone usage
# async def main():
#     """Main function to demonstrate usage"""
#     # Example usage - replace with actual values
#     access_token = "your_access_token_here"
#     sid = "d3847088-4111-4fbc-8b84-df752a5b1e36"
#     jwt_auth_token = "your_jwt_token_here"
#     mpin = os.getenv("MPIN")
    
#     client = KotakFinalSessionClient()
#     session_data = await client.validate_final_session(access_token, sid, jwt_auth_token, mpin)
    
#     if session_data:
#         print("Final session validation successful:")
#         print(json.dumps(session_data, indent=2))
#     else:
#         print("Final session validation failed")

# if __name__ == "__main__":
#     asyncio.run(main())