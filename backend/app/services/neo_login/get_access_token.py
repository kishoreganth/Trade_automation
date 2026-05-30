import os
from typing import Optional, Dict, Any
import logging
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KotakAccessTokenClient:
    """Get Kotak NEO access token from Neo app dashboard (v2 - no OAuth2)"""

    def __init__(self, client_credentials: str = None):
        self._token = client_credentials

    async def get_access_token(self) -> Optional[Dict[str, Any]]:
        """
        Get access token from env (NEO_ACCESS_TOKEN). No OAuth2 - token from Neo app dashboard.
        Returns:
            Dict with access_token key, or None if missing
        """
        token = self._token or os.getenv("NEO_ACCESS_TOKEN")
        if not token:
            logger.error("NEO_ACCESS_TOKEN not found in environment")
            return None
        logger.info("Access token loaded from Neo dashboard (env)")
        return {"access_token": token.strip()}

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







