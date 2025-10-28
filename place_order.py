import aiohttp
import json
import urllib.parse
import ssl
import logging
import time
from pathlib import Path
from neo_login.session_manager import KotakSessionManager
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def _get_order_headers() -> Optional[Dict[str, str]]:
    """Get headers for order placement API calls (similar to get_quote.py)"""
    try:
        # Initialize session manager
        session_manager = KotakSessionManager()
        
        # Load session data
        session_data = await session_manager.load_session()
        
        if not session_data:
            logger.error("No session data found")
            return None
        
        # Extract required tokens
        access_token = session_data.get("access_token")
        sid = session_data.get("sid")
        auth_token = session_data.get("token")
        
        if not all([access_token, sid, auth_token]):
            logger.error("Missing required tokens in session data")
            return None
        
        headers = {
            'accept': 'application/json',
            'Sid': sid,
            'Auth': auth_token,
            'neo-fin-key': 'neotradeapi',
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        return headers
        
    except Exception as e:
        logger.error(f"Error getting order headers: {str(e)}")
        return None

# Get the sid , AUth jwt token from 3_get_final_session.py and use it in the next request
# Get the access token from 1_get_access_token.py and use it in bearer token in the next request


# RIIL-EQ
# INFY-BL

# Import required modules
from gsheet_stock_get import GSheetStockClient
import asyncio
import pandas as pd
from get_quote import get_multiple_quotes, get_single_quote

async def get_gsheet_stocks_df():
    """Get stock data from Google Sheet as pandas DataFrame"""
    client = GSheetStockClient()
    df = await client.get_stock_dataframe()
    
    if df is not None:
        print("\n📊 Stock Data DataFrame from Google Sheet:")

        # Convert to list of dicts for compatibility
        stock_list = df.to_dict('records')

        return df, stock_list
    else:
        print("❌ Failed to fetch stock data from Google Sheet")
        return None, None







async def place_order(order_data):
    """
    Place a single order using Kotak Securities API
    
    Args:
        order_data: Dictionary containing order details
        
    Returns:
        dict: Order response or None if failed
    """
    try:
        # Get authentication headers using session manager (like get_quote.py)
        headers = await _get_order_headers()
        if not headers:
            logger.error("Failed to get authentication headers from session manager")
            return None
        
        # Convert to proper payload format: jData=<URL_encoded_JSON>
        payload = f"jData={urllib.parse.quote(json.dumps(order_data))}"
        
        # Create SSL context for HTTPS
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            async with session.post(
                "https://gw-napi.kotaksecurities.com/Orders/2.0/quick/order/rule/ms/place",
                data=payload,
                headers=headers
            ) as response:
                
                result = await response.text()
                logger.info(f"Order response: {result}")
                
                if response.status == 200:
                    try:
                        return json.loads(result)
                    except json.JSONDecodeError:
                        return {"status": "success", "response": result}
                else:
                    logger.error(f"Order failed with status {response.status}: {result}")
                    return {"status": "error", "code": response.status, "message": result}
                    
    except Exception as e:
        logger.error(f"Exception in place_order: {str(e)}")
        return None


async def place_orders_batch(orders_list, max_concurrent=5):
    """
    Place multiple orders concurrently with rate limiting
    
    Args:
        orders_list: List of order dictionaries
        max_concurrent: Maximum number of concurrent orders (default: 5)
        
    Returns:
        list: List of order responses
    """
    if not orders_list:
        logger.warning("No orders to place")
        return []
    
    # Create semaphore for rate limiting
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def place_single_order(order_data):
        async with semaphore:
            logger.info(f"Placing order: {order_data.get('ts', 'Unknown')} - {order_data.get('tt', 'Unknown')}")
            result = await place_order(order_data)
            # Small delay between orders to be respectful to API
            await asyncio.sleep(0.1)
            return result
    
    # Execute all orders concurrently
    logger.info(f"Placing {len(orders_list)} orders with max {max_concurrent} concurrent requests")
    results = await asyncio.gather(
        *[place_single_order(order) for order in orders_list],
        return_exceptions=True
    )
    
    # Process results
    successful_orders = 0
    failed_orders = 0
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Order {i+1} failed with exception: {str(result)}")
            failed_orders += 1
        elif result and result.get("status") != "error":
            successful_orders += 1
        else:
            failed_orders += 1
    
    logger.info(f"Order batch completed: {successful_orders} successful, {failed_orders} failed")
    return results


async def place_orders_with_rate_limit(orders_list, orders_per_minute=200, max_concurrent=5):
    """
    Place orders with time-windowed rate limiting to respect API limits.
    Executes orders in batches and waits between batches.
    
    Args:
        orders_list: List of order dictionaries
        orders_per_minute: Max orders per minute (default: 200, matching API limit)
        max_concurrent: Concurrent orders within a batch (default: 5)
        
    Returns:
        list: Combined list of all order responses
    """
    if not orders_list:
        logger.warning("No orders to place")
        return []
    
    total_orders = len(orders_list)
    all_results = []
    
    # Split orders into batches of orders_per_minute
    batch_size = orders_per_minute
    total_batches = (total_orders + batch_size - 1) // batch_size  # Ceiling division
    
    logger.info(f"🚀 Starting rate-limited order execution")
    logger.info(f"📊 Total orders: {total_orders}")
    logger.info(f"📦 Batch size: {batch_size} orders/minute")
    logger.info(f"🔢 Total batches: {total_batches}")
    logger.info(f"⏱️ Estimated time: ~{total_batches} minutes")
    
    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, total_orders)
        batch = orders_list[start_idx:end_idx]
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📋 Batch {batch_num + 1}/{total_batches}: Processing orders {start_idx + 1} to {end_idx}")
        logger.info(f"{'='*60}")
        
        # Record batch start time
        batch_start_time = time.time()
        
        # Execute batch
        batch_results = await place_orders_batch(batch, max_concurrent=max_concurrent)
        all_results.extend(batch_results)
        
        # Calculate batch execution time
        batch_elapsed = time.time() - batch_start_time
        logger.info(f"⏱️ Batch {batch_num + 1} completed in {batch_elapsed:.2f} seconds")
        
        # Count successes in this batch
        batch_success = sum(1 for r in batch_results if r and r.get('status') != 'error')
        logger.info(f"✅ Batch {batch_num + 1} success: {batch_success}/{len(batch)} orders")
        
        # Wait remaining time to complete 60-second window (except for last batch)
        if batch_num < total_batches - 1:
            wait_time = max(5, 60 - batch_elapsed)  # Minimum 5s buffer between batches
            if batch_elapsed < 60:
                logger.info(f"⏸️ Waiting {wait_time:.1f} seconds to complete 60-second window...")
            else:
                logger.info(f"⚠️ Batch took {batch_elapsed:.1f}s (>60s) - waiting minimum 5s buffer...")
            await asyncio.sleep(wait_time)
    
    # Final summary
    total_success = sum(1 for r in all_results if r and r.get('status') != 'error')
    total_failed = total_orders - total_success
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🎯 FINAL SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"✅ Successful orders: {total_success}/{total_orders} ({total_success/total_orders*100:.1f}%)")
    logger.info(f"❌ Failed orders: {total_failed}/{total_orders} ({total_failed/total_orders*100:.1f}%)")
    logger.info(f"{'='*60}\n")
    
    return all_results









# ## Create a for loop to place the order for each stock in the gsheets.
async def main():
    df , stocks = await get_gsheet_stocks_df()
    all_rows = []
    if df is not None:
        for index, row in df.iterrows():
                # Convert row to key-value dictionary
                row_dict = row.to_dict()
                all_rows.append(row_dict)
    else:
        print("❌ Failed to get DataFrame")
    print(all_rows)

##### ------ THIS IS TO GET QUOTE FOR EACH STOCK IN THE GSHEET ------ BUT ALREADY CALCULATED IN THE GSHEET SO COMMENTED OUT ------ #####

    # for row in all_rows:
    #     # extract market and exchange token and make to a string like MARKET|ExchangeToken for each row
    #     market = row['MARKET']
    #     exchange_token = row['EXCHANGE_TOKEN']
    #     symbol = f"{market}|{exchange_token}"
        
    #     quote_result = await get_single_quote(symbol)
    #     print(quote_result)
        
    #     # Check if quote_result is valid before accessing it
    #     if quote_result and isinstance(quote_result, list) and len(quote_result) > 0:
    #         print(quote_result[0]["ltp"])
    #         row['LTP'] = quote_result[0]["ltp"]
    #     else:
    #         logger.error(f"Failed to get quote for {symbol}. Skipping this stock.")
    #         print(f"❌ Failed to get quote for {row['STOCK_NAME']} ({symbol})")
    #         continue  # Skip this stock if quote fails
        
    # print(all_rows)

    
    # Collect all orders for batch processing
    all_orders = []
    
    for row in all_rows:
        ## For each stock, place the BUY order 5% below the LTP and place SELL order 5% above the LTP
        # ltp = float(row['LTP'])
        # buy_price = round(ltp * 0.95, 2)
        # sell_price = round(ltp * 1.05, 2)
        
        # refere the params description in the link below
        # https://github.com/Kotak-Neo/Kotak-neo-api-v2/blob/main/docs/Place_Order.md
        # BUY order 
        buy_order = {
            "am": "NO", "dq": "0", "es": "nse_cm", "mp": "0", 
            "pc": "MIS", "pf": "N", "pr": str(row['BUY ORDER']), "pt": "L", 
            "qt": "1", "rt": "DAY", "tp": "0", "ts": row['STOCK_NAME'], "tt": "B"
        }
        
        # SELL order
        sell_order = {
            "am": "NO", "dq": "0", "es": "nse_cm", "mp": "0", 
            "pc": "MIS", "pf": "N", "pr": str(row['SELL ORDER']), "pt": "L", 
            "qt": "1", "rt": "DAY", "tp": "0", "ts": row['STOCK_NAME'], "tt": "S"
        }
        
        all_orders.extend([buy_order, sell_order])
    
    print(f"\n📋 Prepared {len(all_orders)} orders for {len(all_rows)} stocks")
    
    # Place all orders with rate limiting (200 orders per minute = 100 stocks per minute)
    results = await place_orders_with_rate_limit(all_orders, orders_per_minute=200, max_concurrent=5)
    
    # Print summary
    successful = sum(1 for r in results if r and r.get('status') != 'error')
    print(f"\n✅ Order Summary: {successful}/{len(results)} orders successful")

# asyncio.run(main())



# # Order data as dictionary
# # order_data = {"am":"NO", "dq":"0","es":"nse_cm", "mp":"0", "pc":"CNC", "pf":"N", "pt":"MKT", "qt":"1", "rt":"DAY", "tp":"0", "ts":"RIIL-EQ", "tt":"B"}


# # Order data as dictionary
# order_data = {"am":"NO", "dq":"0","es":"nse_cm", "mp":"0", "pc":"CNC", "pf":"N", "pr":"7.72", "pt":"L", "qt":"1", "rt":"DAY", "tp":"0", "ts":"IDEA-EQ", "tt":"S"}
# order_data = {"am":"NO", "dq":"0","es":"nse_cm", "mp":"0", "pc":"CNC", "pf":"N", "pr":"6.98", "pt":"L", "qt":"1", "rt":"DAY", "tp":"0", "ts":"IDEA-EQ", "tt":"B"}

# # BUY SWIGGY-BL
# # order_data = {"am":"NO", "dq":"0","es":"nse_cm", "mp":"0", "pc":"CNC", "pf":"N", "pr":"458", "pt":"L", "qt":"1", "rt":"DAY", "tp":"0", "ts":"SWIGGY-BL", "tt":"S"}
# # # SELL SWIGGY-BL
# # order_data = {"am":"NO", "dq":"0","es":"nse_cm", "mp":"0", "pc":"CNC", "pf":"N", "pr":"415", "pt":"L", "qt":"1", "rt":"DAY", "tp":"0", "ts":"SWIGGY-BL", "tt":"B"}

