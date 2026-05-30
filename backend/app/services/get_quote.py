import asyncio
import aiohttp
import ssl
import json
from typing import List, Dict, Any, Optional, Union
import logging
from urllib.parse import quote
from neo_login.session_manager import KotakSessionManager
from functools import partial
import requests

from gsheet_stock_get import GSheetStockClient
import pandas as pd 
import os 
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

gsheet_stock_client = GSheetStockClient()


class KotakQuoteClient:
    """Async client for Kotak Securities quote API"""
    
    def __init__(self):
        self.session_manager = KotakSessionManager()
    
    async def _get_quote_auth(self) -> Optional[Dict[str, Any]]:
        """Get base_url and headers for quote API (v2: baseUrl + plain token)"""
        try:
            session_data = await self.session_manager.load_session()
            if not session_data:
                logger.error("No session data found")
                return None
            base_url = session_data.get("base_url")
            access_token = session_data.get("access_token")
            if not base_url or not access_token:
                logger.error("Missing base_url or access_token in session")
                return None
            return {
                "base_url": base_url,
                "headers": {'accept': 'application/json', 'Authorization': access_token}
            }
        except Exception as e:
            logger.error(f"Error getting quote auth: {str(e)}")
            return None
        
    async def get_quote(self, symbols: Union[str, List[str]]) -> Optional[Dict[str, Any]]:
        """
        Get quotes for single or multiple symbols
        
        Args:
            symbols: Single symbol string or list of symbols
            
        Returns:
            Dict containing quote data, None if failed
        """
        # Convert list to comma-separated string if needed
        if isinstance(symbols, list):
            symbol_string = ",".join(symbols)
        else:
            symbol_string = symbols
        
        # URL encode the symbols - API requires encoded format
        # Example: nse_cm|2885,bse_cm|532174 becomes nse_cm%7C2885%2Cbse_cm%7C532174
        encoded_symbols = quote(symbol_string, safe='')
        # logger.info(f"Original symbols: {symbol_string}")
        # logger.info(f"URL encoded symbols: {encoded_symbols}")
        
        auth = await self._get_quote_auth()
        if not auth:
            logger.error("Failed to get quote auth")
            return None
        base_url = auth["base_url"]
        headers = auth["headers"]
        url = f"{base_url}/script-details/1.0/quotes/neosymbol/{encoded_symbols}/all"
        # logger.info(f"Calling API URL: {url}")
        
        try:
            # Use requests in executor for truly async non-blocking I/O
            # This is production-grade: non-blocking, concurrent, thread-safe
            loop = asyncio.get_running_loop()
            func = partial(requests.get, url, headers=headers, verify=False, timeout=30)
            response = await loop.run_in_executor(None, func)
            
            if response.status_code == 200:
                data = response.json()
                # logger.info(f"Successfully fetched quotes")
                # logger.info(f"Response type: {type(data)}")
                return data
            else:
                logger.error(f"Quote fetch failed. Status: {response.status_code}, Response: {response.text}")
                return None
                        
        except requests.Timeout:
            logger.error("Request timed out while fetching quotes")
            return None
        except Exception as e:
            logger.error(f"Error fetching quotes: {str(e)}")
            return None
    
    async def get_quotes_concurrent(self, symbol_batches: List[str]) -> List[Optional[Dict[str, Any]]]:
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
    
    async def get_quotes_with_rate_limit(
        self, 
        symbol_batches: List[str], 
        requests_per_minute: int = 190
        ) -> List[Optional[Dict[str, Any]]]:
        """
        Get quotes with rate limiting (190 req/min, 5% under API limit)
        
        Args:
            symbol_batches: List of symbol lists (each inner list = 1 API request)
            requests_per_minute: Max API requests per minute (default: 190)
            
        Returns:
            List of quote data results (preserves order)
        """
        import time
        
        if not symbol_batches:
            logger.warning("No symbol batches to fetch")
            return []
        
        total_requests = len(symbol_batches)
        all_results = []
        
        # Calculate batches based on rate limit (190 = 5% buffer vs 200/min)
        batch_size = min(requests_per_minute, 190)
        total_batches = (total_requests + batch_size - 1) // batch_size
        
        logger.info(f"🚀 Starting rate-limited quote fetching")
        logger.info(f"📊 Total API requests: {total_requests}")
        logger.info(f"📦 Max requests per minute: {batch_size}")
        logger.info(f"🔢 Time windows needed: {total_batches}")
        logger.info(f"⏱️ Estimated time: ~{total_batches} minute(s)")
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, total_requests)
            batch = symbol_batches[start_idx:end_idx]
            
            logger.info(f"\n{'='*60}")
            logger.info(f"📋 Time Window {batch_num + 1}/{total_batches}: Processing API requests {start_idx + 1} to {end_idx}")
            logger.info(f"{'='*60}")
            
            # Record batch start time
            batch_start_time = time.time()
            
            # Execute all API calls in this time window concurrently
            batch_results = await self.get_quotes_concurrent(batch)
            all_results.extend(batch_results)
            
            # Calculate batch execution time
            batch_elapsed = time.time() - batch_start_time
            logger.info(f"⏱️ Time window {batch_num + 1} completed in {batch_elapsed:.2f} seconds")
            
            # Count successes in this batch
            batch_success = sum(1 for r in batch_results if r is not None)
            logger.info(f"✅ Time window {batch_num + 1} success: {batch_success}/{len(batch)} API requests")
            
            # Wait remaining time to complete 60-second window (except for last batch)
            if batch_num < total_batches - 1:
                wait_time = max(5, 60 - batch_elapsed)  # Minimum 5s buffer
                if batch_elapsed < 60:
                    logger.info(f"⏸️ Waiting {wait_time:.1f} seconds to complete 60-second window...")
                else:
                    logger.info(f"⚠️ Batch took {batch_elapsed:.1f}s (>60s) - waiting minimum 5s buffer...")
                await asyncio.sleep(wait_time)
        
        # Final summary
        total_success = sum(1 for r in all_results if r is not None)
        total_failed = total_requests - total_success
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 FINAL SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"✅ Successful API requests: {total_success}/{total_requests} ({total_success/total_requests*100:.1f}%)")
        logger.info(f"❌ Failed API requests: {total_failed}/{total_requests} ({total_failed/total_requests*100:.1f}%)")
        logger.info(f"{'='*60}\n")
        
        return all_results

# Convenience functions
async def get_single_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Get quote for a single symbol"""
    client = KotakQuoteClient()
    return await client.get_quote(symbol)

async def get_multiple_quotes(symbols: List[str]) -> Optional[Dict[str, Any]]:
    """Get quotes for multiple symbols"""
    client = KotakQuoteClient()
    return await client.get_quote(symbols)

async def get_quotes_with_rate_limit(
    symbol_batches: List[str], 
    requests_per_minute: int = 190
) -> List[Optional[Dict[str, Any]]]:
    """
    Get quotes with rate limiting (190 req/min, 5% under API limit)
    
    Args:
        symbol_batches: List of symbol lists (each inner list = 1 API request)
        requests_per_minute: Max API requests per minute (default: 190)
    
    Returns:
        List of quote data results
    """
    client = KotakQuoteClient()
    return await client.get_quotes_with_rate_limit(symbol_batches, requests_per_minute)
  


async def get_gsheet_stocks_df(df):
    """Get stock data from Google Sheet as pandas DataFrame"""

    all_rows = []
    
    if df is not None:
        print("\n📊 Stock Data DataFrame from Google Sheet:")

        # Convert to list of dicts for compatibility
        for index, row in df.iterrows():
            # Convert row to key-value dictionary
            row_dict = row.to_dict()
            all_rows.append(row_dict)
        return all_rows
    else:
        print("❌ Failed to fetch stock data from Google Sheet")
        return None
    
async def get_symbol_from_gsheet_stocks_df(all_rows):
    """
    Create symbols list and track valid row indices with duplicate detection
    Returns: (symbols_list, valid_indices) - only UNIQUE valid symbols, with their first occurrence positions
    Duplicates are skipped to save API calls
    """
    symbols_list = []
    valid_indices = []  # Track which rows have valid data
    seen_tokens = {}  # Track duplicate tokens: {token: first_row_index}
    duplicate_count = 0
    
    for idx, row in enumerate(all_rows):
        # Check if row has valid EXCHANGE_TOKEN and GAP
        token_value = row.get('EXCHANGE_TOKEN')
        gap_value = row.get('GAP')
        
        # Skip rows with invalid/empty EXCHANGE_TOKEN or GAP
        if pd.isna(token_value) or token_value is None or token_value == '' or token_value == 0:
            logger.debug(f"Row {idx}: Skipping - invalid EXCHANGE_TOKEN")
            continue
        
        if pd.isna(gap_value) or gap_value is None or gap_value == '':
            logger.debug(f"Row {idx}: Skipping - invalid GAP")
            continue
        
        # Valid row - convert to symbol
        try:
            exchange_token = int(float(token_value))
            if exchange_token > 0:  # Only valid positive tokens
                # Check for duplicate token
                if exchange_token in seen_tokens:
                    # Duplicate found - skip to save API call
                    duplicate_count += 1
                    logger.debug(f"Row {idx}: Duplicate token {exchange_token} (first seen at row {seen_tokens[exchange_token]}), skipping")
                    continue
                
                # First occurrence - add to fetch list
                symbol = f"nse_cm|{exchange_token}"
                symbols_list.append(symbol)
                valid_indices.append(idx)  # Track original row position
                seen_tokens[exchange_token] = idx  # Mark as seen
        except (ValueError, TypeError):
            logger.debug(f"Row {idx}: Skipping - could not convert EXCHANGE_TOKEN to int")
            continue

    logger.info(f"📊 Created {len(symbols_list)} unique symbols from {len(all_rows)} total rows")
    logger.info(f"📊 Skipped: {len(all_rows) - len(symbols_list)} rows ({duplicate_count} duplicates, {len(all_rows) - len(symbols_list) - duplicate_count} invalid)")
    return symbols_list, valid_indices

async def flatten_quote_result_list(data):
    """
    Flatten nested list structure and preserve fault responses.
    Handles None results from failed API batches gracefully.
    """
    flattened = []
    none_count = 0
    
    for item in data:
        if item is None:
            none_count += 1
            continue
        if isinstance(item, list):
            for sub_item in item:
                if isinstance(sub_item, dict):
                    if 'fault' not in sub_item:
                        flattened.append(sub_item)
                    else:
                        error_dict = {
                            'error': True,
                            'exchange_token': None,
                            'display_symbol': 'INVALID_SYMBOL',
                            'fault_code': sub_item['fault'].get('code', 'unknown'),
                            'fault_message': sub_item['fault'].get('message', 'Unknown error'),
                            'fault_description': sub_item['fault'].get('description', '')
                        }
                        flattened.append(error_dict)
                        logger.warning(f"Invalid symbol: {error_dict['fault_description']}")
                elif sub_item is None:
                    none_count += 1
        elif isinstance(item, dict):
            if 'fault' not in item:
                flattened.append(item)
            else:
                error_dict = {
                    'error': True,
                    'exchange_token': None,
                    'display_symbol': 'INVALID_SYMBOL',
                    'fault_code': item['fault'].get('code', 'unknown'),
                    'fault_message': item['fault'].get('message', 'Unknown error'),
                    'fault_description': item['fault'].get('description', '')
                }
                flattened.append(error_dict)
                logger.warning(f"Invalid symbol: {error_dict['fault_description']}")
    
    valid_count = sum(1 for q in flattened if not q.get('error', False))
    error_count = sum(1 for q in flattened if q.get('error', False))
    logger.info(f"Flattened {len(data)} API responses into {len(flattened)} quotes ({valid_count} valid, {error_count} errors, {none_count} None/dropped)")
    if none_count > 0:
        logger.warning(f"⚠️ {none_count} API batch(es) returned None (timeout/network error) - token-based mapping will handle gaps")
    return flattened

async def fetch_ohlc_from_quote_result(quote_result):
    """Fetch OHLC from quote result"""
    quote_ohlc = []
    for item in quote_result:
        # Use .get() with empty string default to handle missing/None values
        ohlc_data = item.get("ohlc", {})
        single_ohlc = {
            "exchange_token": item.get("exchange_token", ""),
            "display_symbol": item.get("display_symbol", ""),
            "exchange": item.get("exchange", ""),
            "open": ohlc_data.get("open", ""),
            "high": ohlc_data.get("high", ""),
            "low": ohlc_data.get("low", ""),
            "close": ohlc_data.get("close", "")
        }
        quote_ohlc.append(single_ohlc)
    return quote_ohlc

async def update_df_with_quote_ohlc(df, quote_ohlc, valid_indices):
    """
    Update DataFrame with OHLC data using exchange_token matching (not positional).
    Falls back to positional mapping only if token matching fails.
    """
    df['OPEN PRICE'] = None
    
    logger.info(f"📊 Mapping {len(quote_ohlc)} quotes to {len(valid_indices)} valid row positions out of {len(df)} total rows")
    
    # Build token→open_price lookup from API results for O(1) matching
    token_price_map = {}
    zero_price_tokens = []
    for q in quote_ohlc:
        token = q.get('exchange_token', '')
        open_price = q.get('open', '')
        if token and str(token).strip():
            token_key = str(int(float(token)))
            if open_price != '' and open_price is not None:
                price_val = float(open_price)
                if price_val > 0:
                    token_price_map[token_key] = price_val
                else:
                    zero_price_tokens.append(f"{q.get('display_symbol', '?')}(token={token_key})")
    
    if zero_price_tokens:
        logger.warning(f"⚠️ {len(zero_price_tokens)} stocks returned open=0 (pre-market/no trade): {zero_price_tokens[:20]}")
    
    logger.info(f"📊 Token price map built: {len(token_price_map)} valid prices from {len(quote_ohlc)} quotes")
    
    mapped_count = 0
    skipped_count = 0
    token_match_count = 0
    
    for i, idx in enumerate(valid_indices):
        row_token = df.at[idx, 'EXCHANGE_TOKEN'] if 'EXCHANGE_TOKEN' in df.columns else None
        matched = False
        
        if row_token is not None and not pd.isna(row_token):
            token_key = str(int(float(row_token)))
            if token_key in token_price_map:
                df.at[idx, 'OPEN PRICE'] = token_price_map[token_key]
                mapped_count += 1
                token_match_count += 1
                matched = True
        
        if not matched:
            # Fallback: positional mapping (only if token match failed)
            if i < len(quote_ohlc):
                open_price = quote_ohlc[i].get('open', '')
                if open_price != '' and open_price is not None:
                    price_val = float(open_price)
                    if price_val > 0:
                        df.at[idx, 'OPEN PRICE'] = price_val
                        mapped_count += 1
                    else:
                        skipped_count += 1
                else:
                    skipped_count += 1
            else:
                skipped_count += 1
    
    logger.info(f"✅ Mapped {mapped_count} prices ({token_match_count} by token, {mapped_count - token_match_count} by position), skipped {skipped_count}")
    
    # Convert both OPEN PRICE and GAP to numeric (handle string/empty/None values)
    df['OPEN PRICE'] = pd.to_numeric(df['OPEN PRICE'], errors='coerce')
    df['GAP'] = pd.to_numeric(df['GAP'], errors='coerce')
    
    # Calculate BUY ORDER and SELL ORDER based on GAP%
    # BUY ORDER = OPEN PRICE - (GAP% of OPEN PRICE)
    # SELL ORDER = OPEN PRICE + (GAP% of OPEN PRICE)
    # NaN values will be preserved in calculations (invalid rows will have NaN)
    df['BUY ORDER'] = df['OPEN PRICE'] * (1 - df['GAP'] / 100)
    df['SELL ORDER'] = df['OPEN PRICE'] * (1 + df['GAP'] / 100)
    
    # Round to 0 decimal places
    df['BUY ORDER'] = df['BUY ORDER'].round(0)
    df['SELL ORDER'] = df['SELL ORDER'].round(0)
    
    valid_count = df['OPEN PRICE'].notna().sum()
    invalid_count = df['OPEN PRICE'].isna().sum()
    logger.info(f"✅ Updated DataFrame: {valid_count} rows with prices, {invalid_count} rows empty (invalid)")
    
    return df

async def retry_missing_quotes(df, valid_indices, max_retries=2, retry_delay=120):
    """
    Retry fetching quotes for stocks where OPEN PRICE is still NaN (API returned 0 or no data).
    Waits retry_delay seconds between attempts. Only re-fetches missing stocks.
    Returns (updated_df, total_retried_count).
    """
    total_retried = 0
    
    for attempt in range(1, max_retries + 1):
        missing_indices = [idx for idx in valid_indices if pd.isna(df.at[idx, 'OPEN PRICE'])]
        if not missing_indices:
            logger.info(f"✅ No missing prices — retry not needed")
            break
        
        retry_symbols = []
        for idx in missing_indices:
            token = df.at[idx, 'EXCHANGE_TOKEN'] if 'EXCHANGE_TOKEN' in df.columns else None
            if token is not None and not pd.isna(token):
                retry_symbols.append(f"nse_cm|{int(float(token))}")
        
        if not retry_symbols:
            break
        
        logger.info(f"⏳ Retry {attempt}/{max_retries}: {len(retry_symbols)} stocks missing prices, waiting {retry_delay}s...")
        await asyncio.sleep(retry_delay)
        
        batch_size = 190
        retry_batches = [retry_symbols[i:i + batch_size] for i in range(0, len(retry_symbols), batch_size)]
        retry_results = await get_quotes_with_rate_limit(retry_batches, requests_per_minute=190)
        retry_flattened = await flatten_quote_result_list(retry_results)
        retry_ohlc = await fetch_ohlc_from_quote_result(retry_flattened)
        
        # Build token→price map from retry results
        retry_price_map = {}
        for q in retry_ohlc:
            token = q.get('exchange_token', '')
            open_price = q.get('open', '')
            if token and str(token).strip() and open_price != '' and open_price is not None:
                price_val = float(open_price)
                if price_val > 0:
                    retry_price_map[str(int(float(token)))] = price_val
        
        filled = 0
        for idx in missing_indices:
            token = df.at[idx, 'EXCHANGE_TOKEN'] if 'EXCHANGE_TOKEN' in df.columns else None
            if token is not None and not pd.isna(token):
                token_key = str(int(float(token)))
                if token_key in retry_price_map:
                    df.at[idx, 'OPEN PRICE'] = retry_price_map[token_key]
                    filled += 1
        
        total_retried += filled
        logger.info(f"🔄 Retry {attempt}: filled {filled}/{len(retry_symbols)} missing prices")
        
        if filled == len(retry_symbols):
            break
    
    # Recalculate BUY/SELL ORDER after retries
    if total_retried > 0:
        df['OPEN PRICE'] = pd.to_numeric(df['OPEN PRICE'], errors='coerce')
        df['GAP'] = pd.to_numeric(df['GAP'], errors='coerce')
        df['BUY ORDER'] = (df['OPEN PRICE'] * (1 - df['GAP'] / 100)).round(0)
        df['SELL ORDER'] = (df['OPEN PRICE'] * (1 + df['GAP'] / 100)).round(0)
        logger.info(f"✅ Retry complete: {total_retried} additional prices filled")
    
    still_missing = sum(1 for idx in valid_indices if pd.isna(df.at[idx, 'OPEN PRICE']))
    if still_missing > 0:
        logger.warning(f"⚠️ {still_missing} stocks still have no price after all retries")
    
    return df, total_retried

async def write_quote_ohlc_to_gsheet(df, sheet_id, gid="0"):
    """
    Write DataFrame to Google Sheet using gspread
    
    Args:
        df: pandas DataFrame to write
        sheet_id: Google Sheet ID (from URL)
        gid: Sheet/tab GID (default: "0" for first sheet)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info("🔄 Writing DataFrame to Google Sheet...")
        logger.info(f"Sheet ID: {sheet_id}, GID: {gid}")
        logger.info(f"DataFrame shape: {df.shape}")
        
        # Import gspread and credentials
        try:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
        except ImportError:
            logger.error("❌ Missing required packages: gspread, oauth2client")
            logger.error("Install: pip install gspread oauth2client")
            return False
        
        # Set up Google Sheets API credentials
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Load credentials from service account JSON file
        creds_file = 'google_sheets_credentials.json'
        
        if not Path(creds_file).exists():
            logger.error(f"❌ Credentials file not found: {creds_file}")
            logger.error("Please download service account JSON from Google Cloud Console")
            return False
        
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
            client = gspread.authorize(creds)
            logger.info("✅ Authenticated with Google Sheets API")
        except Exception as auth_error:
            logger.error(f"❌ Authentication failed: {str(auth_error)}")
            return False
        
        # Open the spreadsheet
        try:
            spreadsheet = client.open_by_key(sheet_id)
            logger.info(f"✅ Opened spreadsheet: {spreadsheet.title}")
        except Exception as open_error:
            logger.error(f"❌ Failed to open spreadsheet: {type(open_error).__name__}: {str(open_error)}")
            logger.error(f"💡 Ensure service account has access: {creds.service_account_email}")
            return False
        
        # Get the specific worksheet by gid
        try:
            # Find worksheet by gid
            worksheet = None
            for sheet in spreadsheet.worksheets():
                if str(sheet.id) == str(gid):
                    worksheet = sheet
                    break
            
            if worksheet is None:
                # Fallback to first sheet
                worksheet = spreadsheet.get_worksheet(0)
                logger.warning(f"⚠️ GID {gid} not found, using first sheet: {worksheet.title}")
            else:
                logger.info(f"✅ Found worksheet: {worksheet.title}")
        except Exception as sheet_error:
            logger.error(f"❌ Failed to get worksheet: {str(sheet_error)}")
            return False
        
        # Update only specific columns (OPEN PRICE, BUY ORDER, SELL ORDER)
        try:
            import numpy as np
            
            # Read header row to find column positions
            header_row = worksheet.row_values(1)
            logger.info(f"📋 Sheet headers: {header_row}")
            
            # Define columns to update
            columns_to_update = ['OPEN PRICE', 'BUY ORDER', 'SELL ORDER']
            
            # Find column indices (1-based for gspread)
            column_indices = {}
            for col_name in columns_to_update:
                if col_name in header_row:
                    column_indices[col_name] = header_row.index(col_name) + 1
                    logger.info(f"📍 Found column '{col_name}' at index {column_indices[col_name]}")
                else:
                    logger.warning(f"⚠️ Column '{col_name}' not found in sheet")
            
            if not column_indices:
                logger.error("❌ No matching columns found to update")
                return False
            
            # Update each column individually
            for col_name, col_index in column_indices.items():
                if col_name in df.columns:
                    # Get column letter from index
                    col_letter = chr(64 + col_index)  # A=65, B=66, etc.
                    
                    # Prepare data (skip header, start from row 2)
                    values = df[col_name].tolist()
                    # Replace NaN with empty string
                    values = [['' if (isinstance(v, float) and np.isnan(v)) else v] for v in values]
                    
                    # Update range (e.g., 'G2:G12' for OPEN PRICE column)
                    start_row = 2
                    end_row = start_row + len(values) - 1
                    range_name = f"{col_letter}{start_row}:{col_letter}{end_row}"
                    
                    worksheet.update(range_name, values)
                    logger.info(f"✅ Updated column '{col_name}' at range {range_name}")
            
            logger.info(f"✅ Successfully updated {len(column_indices)} columns in Google Sheet")
            return True
            
        except Exception as write_error:
            logger.error(f"❌ Failed to write data: {str(write_error)}")
            try:
                if hasattr(write_error, 'resp') and getattr(write_error, 'resp', None):
                    logger.error(f"   HTTP status: {getattr(write_error.resp, 'status', 'N/A')}")
                if hasattr(write_error, 'content') and getattr(write_error, 'content', None):
                    logger.error(f"   Response: {str(write_error.content)[:500]}")
            except Exception:
                pass
            logger.exception("   Traceback:")
            return False
        
    except Exception as e:
        logger.error(f"❌ Unexpected error in write_quote_ohlc_to_gsheet: {str(e)}")
        return False



async def main():
            
    algo_version = os.getenv("ALGO_VERSION",2)
    if algo_version == 1:
        return "VERSION 1 BHAV DATA AVAILABLE"
    
    sheet_url = f"{os.getenv('BASE_SHEET_URL')}{os.getenv('sheet_gid')}"

    
    df = await gsheet_stock_client.get_stock_dataframe(sheet_url)
    
    all_rows = await get_gsheet_stocks_df(df)

    ##### ------ GET QUOTES WITH RATE LIMITING ------ #####
    symbols_list, valid_indices = await get_symbol_from_gsheet_stocks_df(all_rows)
    
    # Batch symbols (190 per API call) + rate limit 190 req/min
    batch_size = 190
    symbol_batches = [symbols_list[i:i + batch_size] for i in range(0, len(symbols_list), batch_size)]
    quote_result = await get_quotes_with_rate_limit(
        symbol_batches,
        requests_per_minute=190
    )
    print("QUOTE RESULT IS HERE")
    # print(quote_result)
    flattened_quote_result = await flatten_quote_result_list(quote_result)
    print("FLATTENED QUOTE RESULT IS HERE")
    # print(flattened_quote_result)
    
    quote_ohlc = await fetch_ohlc_from_quote_result(flattened_quote_result)
    print("QUOTE OHLC IS HERE")
    print(f"Quote OHLC count: {len(quote_ohlc)}, Valid row indices: {len(valid_indices)}, DataFrame rows: {len(df)}")

    # Update DataFrame with OHLC data, mapping to correct row positions
    df = await update_df_with_quote_ohlc(df, quote_ohlc, valid_indices)

    # Write updated DataFrame back to Google Sheet
    write_success = await write_quote_ohlc_to_gsheet(df, os.getenv("sheet_id"), os.getenv("sheet_gid"))
    
    if write_success:
        logger.info("✅ Successfully updated Google Sheet with OPEN PRICE data")
    else:
        logger.error("❌ Failed to update Google Sheet")