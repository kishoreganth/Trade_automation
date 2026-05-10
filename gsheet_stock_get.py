# Read this public gsheet and get the data and print it. two columsn oen is STOCK NAME and other is GAP 
import aiohttp
import asyncio
import logging
import pandas as pd
from typing import List, Dict, Optional, Union
from io import StringIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GSheetStockClient:
    """Async client for reading stock data from Google Sheet"""
    
    def __init__(self):
        # Published Google Sheet URL in CSV format
        # Note: Sheet must be made public for this to work
        self.sheet_url = "https://docs.google.com/spreadsheets/d/1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM/export?format=csv&gid=0"

    async def get_stock_data(self) -> Optional[List[Dict[str, str]]]:
        """
        Fetch stock data from published Google Sheet
        
        Returns:
            List of dicts containing stock name and gap values, or None if failed
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.sheet_url) as response:
                    if response.status == 200:
                        # Read CSV data
                        csv_text = await response.text()
                        
                        # Parse CSV rows
                        stocks = []
                        rows = csv_text.strip().split('\n')
                        
                        # Skip header row and process data rows
                        for row in rows[1:]:
                            cols = row.split(',')
                            if len(cols) >= 2:
                                stocks.append({
                                    'stock_name': cols[0].strip(),
                                    'gap': cols[1].strip()
                                })
                            
                        logger.info(f"Successfully fetched {len(stocks)} stocks")
                        return stocks
                        
                    else:
                        logger.error(f"Failed to fetch sheet data. Status: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching stock data: {str(e)}")
            return None
    
    async def get_stock_dataframe(self,sheet_url:str) -> Optional[pd.DataFrame]:
        """
        Fetch stock data from published Google Sheet as pandas DataFrame
        
        Returns:
            pandas DataFrame with columns: STOCK_NAME, EXCHANGE_TOKEN, GAP, MARKET, QUANTITY
            or None if failed
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(sheet_url) as response:
                    if response.status == 200:
                        # Read CSV data directly into pandas DataFrame
                        csv_text = await response.text()
                        
                        # Create DataFrame from CSV
                        df = pd.read_csv(StringIO(csv_text))
                        
                        # Clean column names (remove extra spaces)
                        df.columns = df.columns.str.strip()
                        
                        # Convert GAP to numeric (handle % values)
                        if 'GAP' in df.columns:
                            # Remove '%' symbol and convert to numeric
                            df['GAP'] = df['GAP'].astype(str).str.replace('%', '').str.strip()
                            df['GAP'] = pd.to_numeric(df['GAP'], errors='coerce')
                        
                        # Convert QUANTITY to numeric if possible
                        if 'QUANTITY' in df.columns:
                            df['QUANTITY'] = pd.to_numeric(df['QUANTITY'], errors='coerce').fillna(0)
                        
                        # Convert OPEN PRICE to numeric if exists
                        if 'OPEN PRICE' in df.columns:
                            df['OPEN PRICE'] = pd.to_numeric(df['OPEN PRICE'], errors='coerce')
                        
                        # Convert BUY ORDER to numeric if exists
                        if 'BUY ORDER' in df.columns:
                            df['BUY ORDER'] = pd.to_numeric(df['BUY ORDER'], errors='coerce')
                        
                        # Convert SELL ORDER to numeric if exists
                        if 'SELL ORDER' in df.columns:
                            df['SELL ORDER'] = pd.to_numeric(df['SELL ORDER'], errors='coerce')
                        
                        logger.info(f"Successfully fetched DataFrame with {len(df)} rows and {len(df.columns)} columns")
                        logger.info(f"Columns: {list(df.columns)}")
                        
                        return df
                        
                    else:
                        logger.error(f"Failed to fetch sheet data. Status: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching stock dataframe: {str(e)}")
            return None
    
    # async def get_stock_data_enhanced(self) -> Optional[List[Dict[str, Union[str, int, float]]]]:
    #     """
    #     Fetch stock data with enhanced type handling
        
    #     Returns:
    #         List of dicts with proper data types, or None if failed
    #     """
    #     df = await self.get_stock_dataframe()
        
    #     if df is not None:
    #         # Convert DataFrame to list of dictionaries with proper types
    #         return df.to_dict('records')
        
    #     return None

async def main():
    """Main function to demonstrate usage"""
    client = GSheetStockClient()
    
    print("🔍 Fetching stock data as DataFrame...")
    df = await client.get_stock_dataframe()
    
    if df is not None:
        print("\n📊 Stock Data DataFrame:")
        print("=" * 60)
        print(df.to_string(index=False))
        
        print(f"\n📈 DataFrame Info:")
        print(f"   Rows: {len(df)}")
        print(f"   Columns: {list(df.columns)}")
        print(f"   Data Types:\n{df.dtypes}")
        
        # Show some DataFrame operations
        if 'GAP' in df.columns:
            print(f"\n🔢 GAP Statistics:")
            print(f"   Mean GAP: {df['GAP'].mean():.2f}")
            print(f"   Max GAP: {df['GAP'].max()}")
            print(f"   Min GAP: {df['GAP'].min()}")
            
            # Filter high gap stocks
            high_gap = df[df['GAP'] >= 5]
            if not high_gap.empty:
                print(f"\n🔥 High GAP Stocks (>= 5):")
                print(high_gap[['STOCK NAME', 'GAP']].to_string(index=False))
        
        print(f"\n📋 Enhanced Data (List of Dicts):")
        enhanced_data = await client.get_stock_data_enhanced()
        if enhanced_data:
            for i, stock in enumerate(enhanced_data[:3], 1):  # Show first 3
                print(f"   {i}. {stock}")
        
    else:
        print("❌ Failed to fetch stock data")

# Convenience functions for easy usage
async def get_stocks_df() -> Optional[pd.DataFrame]:
    """Convenience function to get stock DataFrame"""
    client = GSheetStockClient()
    return await client.get_stock_dataframe()

async def get_stocks_dict() -> Optional[List[Dict[str, Union[str, int, float]]]]:
    """Convenience function to get stock data as list of dicts"""
    client = GSheetStockClient()
    return await client.get_stock_data_enhanced()

if __name__ == "__main__":
    asyncio.run(main())

