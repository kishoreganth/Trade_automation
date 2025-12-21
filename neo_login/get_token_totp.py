import asyncio
import aiohttp
import json
import ssl
from typing import Optional, Dict, Any
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KotakTOTPClient:
    """Async client for TOTP-based login to Kotak Securities"""
    
    def __init__(self):
        self.base_url = "https://gw-napi.kotaksecurities.com"
        
    async def login_with_totp(
        self, 
        access_token: str, 
        mobile_number: str, 
        ucc: str, 
        totp: str
    ) -> Optional[Dict[str, Any]]:
        """
        Login with TOTP to Kotak Securities API
        
        Args:
            access_token: Bearer token from access token API
            mobile_number: Mobile number (with country code, e.g., '+919841198942')
            ucc: User Client Code
            totp: Time-based One-Time Password
            
        Returns:
            Dict containing login response data, or None if failed
        """
        # Create SSL context that allows unverified certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        payload = {
            "mobileNumber": mobile_number,
            "ucc": ucc,
            "totp": totp
        }
        
        headers = {
            'Authorization': f"Bearer {access_token}",
            'neo-fin-key': 'neotradeapi',
            'Content-Type': 'application/json'
        }
        
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=120, connect=60)) as session:
                async with session.post(
                    f"{self.base_url}/login/1.0/login/v6/totp/login",
                    json=payload,
                    headers=headers
                ) as response:
                    
                    response_text = await response.text()
                    
                    if response.status == 200:
                        logger.info(f"Successfully logged in with TOTP for UCC: {ucc}")
                        
                        try:
                            login_data = json.loads(response_text)
                            return login_data
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse JSON response: {response_text}")
                            return None
                    else:
                        logger.error(f"TOTP login failed. Status: {response.status}, Response: {response_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("Request timed out while logging in with TOTP")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during TOTP login: {str(e)}")
            return None

# Convenience function for standalone usage
async def login_with_totp(access_token: str, mobile_number: str, ucc: str, totp: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to login with TOTP
    
    Args:
        access_token: Bearer token from access token API
        mobile_number: Mobile number (with country code)
        ucc: User Client Code
        totp: Time-based One-Time Password
        
    Returns:
        Dict containing login response data, or None if failed
    """
    client = KotakTOTPClient()
    return await client.login_with_totp(access_token, mobile_number, ucc, totp)

# # Main async function for standalone usage
# async def main():
#     """Main function to demonstrate usage"""
#     # Example usage - replace with actual values
#     access_token = "your_access_token_here"
#     mobile_number = os.getenv("MOBILE_NUMBER")
#     ucc = os.getenv("UCC")
#     totp = os.getenv("TOTP")
    
#     client = KotakTOTPClient()
#     login_data = await client.login_with_totp(access_token, mobile_number, ucc, totp)
    
#     if login_data:
#         print("TOTP login successful:")
#         print(json.dumps(login_data, indent=2))
#     else:
#         print("TOTP login failed")

# if __name__ == "__main__":
#     asyncio.run(main())