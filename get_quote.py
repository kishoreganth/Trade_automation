import asyncio
import aiohttp
import ssl
import json
from typing import List, Dict, Any, Optional, Union
import logging
from urllib.parse import quote
from neo_login.session_manager import KotakSessionManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KotakQuoteClient:
    """Async client for Kotak Securities quote API"""
    
    def __init__(self):
        self.base_url = "https://gw-napi.kotaksecurities.com"
        self.session_manager = KotakSessionManager()
    
    async def _get_quote_headers(self) -> Optional[Dict[str, str]]:
        """Get headers for quote API calls"""
        try:
            # Load session data
            session_data = await self.session_manager.load_session()
            
            if not session_data:
                logger.error("No session data found")
                return None
            
            access_token = session_data.get("access_token")
            
            if not access_token:
                logger.error("Access token not found in session data")
                return None
            
            headers = {
                'accept': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            
            return headers
            
        except Exception as e:
            logger.error(f"Error getting quote headers: {str(e)}")
            return None
        
    async def get_quote(self, symbols: Union[str, List[str]]) -> Optional[Dict[str, Any]]:
        """
        Get quotes for single or multiple symbols
        
        Args:
            symbols: Single symbol string or list of symbols
            
        Returns:
            Dict containing quote data, None if failed
        """
        # if isinstance(symbols, str):
        #     symbols = [symbols]
        
        # Format symbols for API
        # symbol_string = ",".join(symbols)
        symbol_string = symbols
        # URL encode the symbols - API requires encoded format
        # Example: nse_cm|2885,bse_cm|532174 becomes nse_cm%7C2885%2Cbse_cm%7C532174
        encoded_symbols = quote(symbol_string, safe='')
        logger.info(f"Original symbols: {symbol_string}")
        logger.info(f"URL encoded symbols: {encoded_symbols}")
        
        # Get headers from session manager
        headers = await self._get_quote_headers()
        if not headers:
            logger.error("Failed to get authentication headers")
            return None
        
        # Create SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        try:
            async with aiohttp.ClientSession(
                connector=connector, 
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                
                # Debug: Print the URL being called
                url = f"{self.base_url}/apim/quotes/1.0/quotes/neosymbol/{encoded_symbols}/ltp"
                logger.info(f"Calling API URL: {url}")
                

                
                async with session.get(
                    url,
                    headers=headers
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Successfully fetched quotes")
                        logger.info(f"Response type: {type(data)}")
                        return data
                    else:
                        error_text = await response.text()
                        logger.error(f"Quote fetch failed. Status: {response.status}, Response: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("Request timed out while fetching quotes")
            return None
        except Exception as e:
            logger.error(f"Error fetching quotes: {str(e)}")
            return None
    
    async def get_quotes_concurrent(self, symbol_batches: List[List[str]]) -> List[Optional[Dict[str, Any]]]:
        """
        Get quotes for multiple batches concurrently
        
        Args:
            symbol_batches: List of symbol lists for concurrent processing
            
        Returns:
            List of quote data results
        """
        tasks = [self.get_quote(batch) for batch in symbol_batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and return results
        return [result if not isinstance(result, Exception) else None for result in results]

# Convenience functions
async def get_single_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Get quote for a single symbol"""
    client = KotakQuoteClient()
    return await client.get_quote(symbol)

async def get_multiple_quotes(symbols: List[str]) -> Optional[Dict[str, Any]]:
    """Get quotes for multiple symbols"""
    client = KotakQuoteClient()
    return await client.get_quote(symbols)

async def get_quotes_batch(symbol_batches: List[List[str]]) -> List[Optional[Dict[str, Any]]]:
    """Get quotes for multiple batches concurrently"""
    client = KotakQuoteClient()
    return await client.get_quotes_concurrent(symbol_batches)
  
  
# print(asyncio.run(get_single_quote("bse_cm|532174,bse_cm|543220")))