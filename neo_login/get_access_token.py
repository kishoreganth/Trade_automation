import asyncio
import aiohttp
import json
import ssl
from typing import Optional, Dict, Any
import logging
from dotenv import load_dotenv
import os 

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KotakAccessTokenClient:
    """Async client for getting Kotak Securities access token"""
    
    def __init__(self,client_credentials: str = None):
        self.base_url = "https://napi.kotaksecurities.com"
        # self.client_credentials = f'Basic {os.getenv("CLIENT_CREDENTIALS")}'
        self.client_credentials = client_credentials
        
    async def get_access_token(self) -> Optional[Dict[str, Any]]:
        """
        Get access token from Kotak Securities API
        
        Returns:
            Dict containing access token and related info, or None if failed
        """
        # Create SSL context that allows unverified certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        payload = 'grant_type=client_credentials'
        headers = {
            'Authorization': self.client_credentials,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(
                    f"{self.base_url}/oauth2/token",
                    data=payload,
                    headers=headers
                ) as response:
                    
                    if response.status == 200:
                        response_data = await response.text()
                        logger.info(f"Successfully received access token response")
                        
                        try:
                            token_data = json.loads(response_data)
                            return token_data
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse JSON response: {response_data}")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to get access token. Status: {response.status}, Response: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("Request timed out while getting access token")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while getting access token: {str(e)}")
            return None

# Main async function for standalone usage
# async def main():
#     """Main function to demonstrate usage"""
#     client = KotakAccessTokenClient()
#     token_data = await client.get_access_token()
    
#     if token_data:
#         print("Access token retrieved successfully:")
#         print(type(token_data))
#         print(token_data["access_token"])
#         print(json.dumps(token_data, indent=2))
#     else:
#         print("Failed to retrieve access token")

# if __name__ == "__main__":
#     asyncio.run(main())







