from nsepython import *
import asyncio
# import nsepythonserver
import csv
import requests
import os
import json
import pandas as pd
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import httpx
import aiofiles
import aiofiles.os
import io
from contextlib import asynccontextmanager
import logging

from stock_info import SME_companies, BSE_NSE_companies

## TELEGRAM SETUP
TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = "http://122.165.113.41:5000/webhook"  # Make sure the path matches Flask's route
chat_ids = ["776062518", "@test_kishore_ai_chat"]
# chat_id = "@test_kishore_ai_chat"

equity_url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
sme_url = "https://www.nseindia.com/api/corporate-announcements?index=sme"

# Create the FastAPI app
app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up logging to both file and console
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# File handler
file_handler = logging.FileHandler('app.log')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# Add both handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Store task references globally
sme_task = None
equities_task = None

csv_file_path = "files/all_corporate_announcements.csv"
watchlist_CA_files = "files/watchlist_corporate_announcements.csv"
# chat_id = "@test_kishore_ai_chat"
TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"

# "fundraisensebse"




gsheet_chats = "1v35Bq76X3_gA00uZan5wa0TOP60F-AHJVSCeHCPadD0"
sheet_id = gsheet_chats

# Keyword _custom group
gid = "1091746650"
keyword_custom_group_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


watchlist_sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"



async def send_webhook_message(chat_id: int, text: str):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            # print(f"Message sent to {chat_id}: {text}")
        except httpx.RequestError as e:
            print(f"Error sending message: {e}")


async def set_webhook():
    url = f"{TELEGRAM_API_URL}/setWebhook"
    payload = {"url": WEBHOOK_URL}

    try:
        response = httpx.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("ok"):
            print(f"Webhook set successfully: {data}")
        else:
            print(f"Failed to set webhook: {data}")
    except httpx.RequestError as e:
        print(f"Error setting webhook: {e}")


async def search_csv(all_keywords):
    # List to store results
    results = []
    seen_rows = set()  # To track unique rows

    # Convert string input to list if needed
    if isinstance(all_keywords, str):
        all_keywords = [all_keywords]
    elif not isinstance(all_keywords, list):
        all_keywords = [str(all_keywords)]

    # logger.info(f"Starting search for keywords: {all_keywords}")
    
    try:
        with open(csv_file_path, mode="r", encoding="utf-8") as file:
            reader = csv.reader(file)
            
            # Skip header row
            next(reader, None)
            
            # Iterate through rows
            for row in reader:
                # Create a unique identifier for the row
                row_id = tuple(row)
                
                # Skip if we've already seen this row
                if row_id in seen_rows:
                    continue
                
                # Check if any of the keywords exists in any cell of the row
                if any(any(kw in str(cell).lower() for kw in all_keywords) for cell in row):
                    results.append({
                        "row": row,
                    })
                    seen_rows.add(row_id)
                    
        # logger.info(f"Search completed. Found {len(results)} unique results")
        return results
        
    except Exception as e:
        # logger.error(f"Error in search_csv: {str(e)}")
        return []




async def trigger_watchlist_message(message):
    print("WATCHLIST stocks are sending to telegram")
    
    df = pd.read_csv(watchlist_sheet_url)
    print(df)

    watchlist_chat_ids = []
    print("these are the watchlist chat ids - ", watchlist_chat_ids)

    for index, row in df.iterrows():
        print("row is - ", row)
        chat_id = "@" + str(row['Telegram link'])
        print("CHAT ID IS - ", chat_id)
        watchlist_chat_ids.append(chat_id)

    print("WATCHLIST CHAT IDS ARE - ", watchlist_chat_ids)
    
    for chat_id in watchlist_chat_ids:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        logger.info(f"Triggered message: {message}")

        r = requests.post(url, json=payload)
    # print(r.json())


# this is the test message to see if the script is working or not
# This will send all the CA docs to the trade_mvd chat id ( which is our Script CA running telegram )
async def trigger_test_message(chat_idd, message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_idd,
        "text": message,
        "parse_mode": "HTML"
    }
    # logger.info(f"Triggered test message: {message}")
    print("triggered", chat_idd, "  -- message is ", message)
    r = requests.post(url, json=payload)




async def process_ca_data(ca_docs):
    """Process the corporate announcements data and update CSV files"""
    if await aiofiles.os.path.exists(csv_file_path):
        logger.info(f"Processing existing file: {csv_file_path}")
        async with aiofiles.open(csv_file_path, mode='r') as f:
            content = await f.read()
            df1 = pd.read_csv(io.StringIO(content), dtype='object')
            
        df2 = pd.DataFrame(ca_docs)
        async with aiofiles.open("files/temp.csv", mode='w') as f:
            await f.write(df2.to_csv(index=False))
        
        async with aiofiles.open("files/temp.csv", mode='r') as f:
            content = await f.read()
            api_df = pd.read_csv(io.StringIO(content), dtype='object')
        
        # Convert all columns to string and strip whitespace
        df1 = df1.map(str).map(lambda x: x.strip() if isinstance(x, str) else x)
        api_df = api_df.map(str).map(lambda x: x.strip() if isinstance(x, str) else x)
        
        # Find new rows
        merged = pd.merge(df1, api_df, how='outer', indicator=True)
        merged = merged.sort_values(by='an_dt', ascending=False)
        new_rows = merged[merged['_merge'] == 'right_only'].drop('_merge', axis=1)
        
        #if new rows  
        if len(new_rows) > 0:
            try:
                group_keyword_df = pd.read_csv(keyword_custom_group_url)
                print(group_keyword_df)
                group_id_keywords = {}
                # for index, row in group_keyword_df.iterrows():
                #     print("row is - ", row)
                #     group_id = "@" + str(row['group_id'])
                #     group_id_keywords[group_id] = row['keywords']
                    
                for index, row in group_keyword_df.iterrows():
                    group_id = "@" + str(row['group_id']).strip()
                    keywords_str = str(row['keywords']) if pd.notna(row['keywords']) else ""
                    # Split by comma and strip each keyword
                    keywords = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
                    group_id_keywords[group_id] = keywords
                print("these are the group id and keywords - ", group_id_keywords)
            except Exception as e:
                logger.error(f"Error reading Google Sheet: {str(e)}")
                logger.info("Continuing without custom group keywords due to sheet being edited or unavailable")
                group_id_keywords = {}  # Set empty dict to continue processing without custom groups


            # group_id_keywords = {}
            # group_id_keywords["@test_and_q"] = ["exchange"]
            # group_id_keywords["@test_and_k"] = ["updates", "general"]

            # now we need to check if the new_rows is in the group_id_keywords
            for group_id, keywords in group_id_keywords.items():
                # Convert keywords to lowercase list
                keywords_lower = [str(kw).lower() for kw in keywords]
                
                # Check if any keyword exists in any column of the row  
                for index, row in new_rows.iterrows():
                    # Convert all row values to lowercase strings and check for keyword matches
                    row_values = [str(val).lower() for val in row]
                    if any(any(kw in val for val in row_values) for kw in keywords_lower):
                        message = f"""<b>{row['symbol']} - {row['sm_name']}</b>\n\n{row['desc']}\n\n<i>{row['attchmntText']}</i>\n\n<b>File:</b>\n{row['attchmntFile']}"""
                        await trigger_test_message(group_id, message)

            for index, row in new_rows.iterrows():

                message = f"""<b>{row['symbol']} - {row['sm_name']}</b>\n\n{row['desc']}\n\n<i>{row['attchmntText']}</i>\n\n<b>File:</b>\n{row['attchmntFile']}"""

                # message = f"""<b>{symbol} - {sm_name}</b>\n\n{desc}\n\n<i>{attached_text}</i>\n\n<b>File:</b>\n{attached_file}"""
                await trigger_test_message("@trade_mvd", message)
                
                # check if the company is in the SME list
                if row["sm_name"] in SME_companies:
                    await trigger_watchlist_message(message)
                    await update_watchlist_file(new_rows)
                # check if the company is in the BSE_NSE_companies list
                if row["sm_name"] in BSE_NSE_companies:
                    await trigger_watchlist_message(message)
                    await update_watchlist_file(new_rows)
                    
            # Update main CSV file
            df1_updated = pd.concat([new_rows, df1], ignore_index=True).drop_duplicates()
            async with aiofiles.open(csv_file_path, mode='w') as f:
                await f.write(df1_updated.to_csv(index=False))
            
        return 1
    else:
        logger.info(f"Creating new file: {csv_file_path}")
        df = pd.DataFrame(ca_docs)
        async with aiofiles.open(csv_file_path, mode='w') as f:
            await f.write(df.to_csv(index=False))
        return 1

async def update_watchlist_file(new_rows):
    """Update the watchlist CSV file with new rows"""
    if await aiofiles.os.path.exists(watchlist_CA_files):
        logger.info(f"Appending to existing watchlist file: {watchlist_CA_files}")
        async with aiofiles.open(watchlist_CA_files, mode='a') as f:
            await f.write(new_rows.to_csv(index=False, header=False))
    else:
        logger.info(f"Creating new watchlist file: {watchlist_CA_files}")
        async with aiofiles.open(watchlist_CA_files, mode='w') as f:
            await f.write(new_rows.to_csv(index=False))



async def CA_sme():
    """
    Fetches corporate announcements data using two methods:
    1. Primary method using nsefetch
    2. Fallback method using httpx.AsyncClient with improved session handling
    If both methods fail, waits 60 seconds before retrying
    """
    # Test exception handling
    # if test_exception:
        # if test_exception == 'json_decode':
        # elif test_exception == 'http_error':
        #     raise httpx.HTTPStatusError("Test HTTP error", request=None, response=None)
        # elif test_exception == 'empty_response':
        #     raise ValueError("Empty response from NSE API")
        # elif test_exception == 'unauthorized':
        #     raise ValueError("NSE API returned 401 Unauthorized. Access might be blocked.")
        # else:
        #     raise ValueError(f"Invalid test exception type: {test_exception}")

    # Method 1: Using nsefetch
    try:
        logger.info("Attempting to fetch data using nsefetch...")
        # raise json.JSONDecodeError("Test JSON decode error", "", 0)

        ca_docs = nsefetch(sme_url)
        logger.info(f"Successfully fetched data using nsefetch. Type: {type(ca_docs)}")
        return await process_ca_data(ca_docs)
        
    except (requests.exceptions.JSONDecodeError, json.JSONDecodeError) as e:
        logger.error(f"JSON Decode Error in nsefetch method: {str(e)}")
        # Method 2: Using httpx.AsyncClient with improved session handling
        try:
            logger.info("Attempting fallback method using httpx.AsyncClient with improved session handling...")
            # headers = {
            #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            #     "Accept-Language": "en-US,en;q=0.9",
            #     "Accept-Encoding": "gzip, deflate, br",
            #     "Connection": "keep-alive",
            # }
            # More comprehensive headers that mimic a real browser
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Referer": "https://www.nseindia.com/",
                "Origin": "https://www.nseindia.com",
                "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache"
            }
            
            
            # Create a session with cookies
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                # First, visit the main page to get cookies
                logger.info("Visiting main NSE page to get cookies...")
                main_page_response = await client.get("https://www.nseindia.com/", headers=headers)
                
                # Add a small delay to mimic human behavior
                await asyncio.sleep(2)
                
                # Now make the actual API request with the same session (cookies will be maintained)
                logger.info("Making API request with session cookies...")
                response = await client.get(sme_url, headers=headers)
                
                # Log the response status and headers for debugging
                logger.info(f"Response status: {response.status_code}")
                # logger.info(f"Response headers: {dict(response.headers)}")
                
                # Check if response is empty
                if not response.text:
                    logger.error("Empty response received from NSE API")
                    raise ValueError("Empty response from NSE API")
                
                # Check if we got a 401 Unauthorized
                if response.status_code == 401:
                    logger.error("Received 401 Unauthorized. NSE might be blocking automated access.")
                    # logger.error(f"Response text: {response.text[:200]}...")
                    raise ValueError("NSE API returned 401 Unauthorized. Access might be blocked.")
                    
                # Try to parse JSON
                try:
                    data = response.json()
                    if not data:
                        logger.error("Empty JSON data received from NSE API")
                        raise ValueError("Empty JSON data from NSE API")
                    return await process_ca_data(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {str(e)}")
                    logger.error(f"Response text: {response.text[:200]}...")  # Log first 200 chars of response
                    raise
                
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Status Error in fallback method: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in fallback method: {str(e)}")
            raise
            
    except Exception as e:
        logger.error(f"Unexpected error in CA_equities: {str(e)}")
        logger.info("Both methods failed. Waiting 30 seconds before retrying...")
        await asyncio.sleep(20)
        return None





## THIS IS to get input message for the AI bot in the telegram, I response based on the previous data 
@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        # print(f"Incoming data: {data}")  # Log data for debugging
        # print(data)
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")

            if text:
                # Respond to the user
                ## search from the existing files of equity
                results = await search_csv(text)
                # print(results)
                # print("\n")
                print("Total records found - ", len(results))
                # print(type(results))
                if len(results) > 0:
                    for i in range(len(results)):
                        # print(results[i])
                        symbol = results[i]["row"][0]
                        sm_name = results[i]["row"][4]
                        desc = results[i]["row"][1]
                        attached_text = results[i]["row"][11]
                        attached_file = results[i]["row"][3]

                        final_message = f"""<b>{symbol} - {sm_name}</b>\n\n{desc}\n\n<i>{attached_text}</i>\n\n<b>File:</b>\n{attached_file}"""
                        await send_webhook_message(chat_id, final_message)

            else:
                await send_webhook_message(chat_id, "I can only process text messages right now.")

        return {"status": "ok"}
    except Exception as e:
        print(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")



# Function to run the periodic task
async def run_periodic_task_sme():
    logger.info("starting thescript sme")
    while True:
        try:
            logger.info("starting")
            print("starting")
            result = await CA_sme()  # Run the task
            
            if result is None:
                logger.warning("Failed to fetch data, will retry in next cycle")
            else:
                logger.info("Successfully fetched data")
                # Process results here if needed
                
            logger.info("next loop")
            print("next loop")
            # Slightly increase wait time to avoid hitting rate limits
            await asyncio.sleep(10)  # Wait for 10 seconds before running it again
        except Exception as e:
            logger.error(f"Error in run_periodic_task sme: {str(e)}")
            logger.info("Error occurred, waiting 30 seconds before retrying...")
            await asyncio.sleep(30)  # Wait for 60 seconds before retrying


# X--- X --- X --- X --- X --- X 
#  EQUITiES 
# X--- X --- X --- X --- X --- X 


async def CA_equities():
    """
    Fetches corporate announcements data using two methods:
    1. Primary method using nsefetch
    2. Fallback method using httpx.AsyncClient with improved session handling
    If both methods fail, waits 60 seconds before retrying
    """
    # Test exception handling
    # if test_exception:
        # if test_exception == 'json_decode':
        # elif test_exception == 'http_error':
        #     raise httpx.HTTPStatusError("Test HTTP error", request=None, response=None)
        # elif test_exception == 'empty_response':
        #     raise ValueError("Empty response from NSE API")
        # elif test_exception == 'unauthorized':
        #     raise ValueError("NSE API returned 401 Unauthorized. Access might be blocked.")
        # else:
        #     raise ValueError(f"Invalid test exception type: {test_exception}")

    # Method 1: Using nsefetch
    try:
        logger.info("Attempting to fetch data using nsefetch...")
        # raise json.JSONDecodeError("Test JSON decode error", "", 0)

        ca_docs = nsefetch(equity_url)
        logger.info(f"Successfully fetched data using nsefetch. Type: {type(ca_docs)}")
        return await process_ca_data(ca_docs)
        
    except (requests.exceptions.JSONDecodeError, json.JSONDecodeError) as e:
        logger.error(f"JSON Decode Error in nsefetch method: {str(e)}")
        # Method 2: Using httpx.AsyncClient with improved session handling
        try:
            logger.info("Attempting fallback method using httpx.AsyncClient with improved session handling...")
            
            # More comprehensive headers that mimic a real browser
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Referer": "https://www.nseindia.com/",
                "Origin": "https://www.nseindia.com",
                "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache"
            }
            
            
            # Create a session with cookies
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                # First, visit the main page to get cookies
                logger.info("Visiting main NSE page to get cookies...")
                main_page_response = await client.get("https://www.nseindia.com/", headers=headers)
                
                # Add a small delay to mimic human behavior
                await asyncio.sleep(2)
                
                # Now make the actual API request with the same session (cookies will be maintained)
                logger.info("Making API request with session cookies...")
                response = await client.get(equity_url, headers=headers)
                
                # Log the response status and headers for debugging
                logger.info(f"Response status: {response.status_code}")
                # logger.info(f"Response headers: {dict(response.headers)}")
                
                # Check if response is empty
                if not response.text:
                    logger.error("Empty response received from NSE API")
                    raise ValueError("Empty response from NSE API")
                
                # Check if we got a 401 Unauthorized
                if response.status_code == 401:
                    logger.error("Received 401 Unauthorized. NSE might be blocking automated access.")
                    # logger.error(f"Response text: {response.text[:200]}...")
                    raise ValueError("NSE API returned 401 Unauthorized. Access might be blocked.")
                    
                # Try to parse JSON
                try:
                    data = response.json()
                    if not data:
                        logger.error("Empty JSON data received from NSE API")
                        raise ValueError("Empty JSON data from NSE API")
                    return await process_ca_data(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {str(e)}")
                    logger.error(f"Response text: {response.text[:200]}...")  # Log first 200 chars of response
                    raise
                
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Status Error in fallback method: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in fallback method: {str(e)}")
            raise
            
    except Exception as e:
        logger.error(f"Unexpected error in CA_equities: {str(e)}")
        logger.info("Both methods failed. Waiting 30 seconds before retrying...")
        await asyncio.sleep(20)
        return None


# Function to run the periodic task
async def run_periodic_task_equities():
    logger.info("starting thescript equities ")
    while True:
        try:
            logger.info("starting")
            print("starting")
            result = await CA_equities()  # Run the task
            
            if result is None:
                logger.warning("Failed to fetch data, will retry in next cycle")
            else:
                logger.info("Successfully fetched data")
                # Process results here if needed
                
            logger.info("next loop")
            print("next loop")
            # Slightly increase wait time to avoid hitting rate limits
            await asyncio.sleep(10)  # Wait for 10 seconds before running it again
        except Exception as e:
            logger.error(f"Error in run_periodic_task_equities: {str(e)}")
            logger.info("Error occurred in Equities task, waiting 30 seconds before retrying...")
            await asyncio.sleep(30)  # Wait for 30 seconds before retrying

# Start the background tasks when the application starts
@app.on_event("startup")
async def startup_event():
    global sme_task, equities_task
    # Start both tasks in parallel using asyncio.create_task
    sme_task = asyncio.create_task(run_periodic_task_sme())
    equities_task = asyncio.create_task(run_periodic_task_equities())
    print("Both SME and Equities background tasks are now running in parallel")
    logger.info("Both SME and Equities background tasks are now running in parallel")

# Clean up tasks when the application shuts down
@app.on_event("shutdown")
async def shutdown_event():
    global sme_task, equities_task
    # Cancel the SME task if it's still running
    if sme_task and not sme_task.done():
        sme_task.cancel()
        try:
            await sme_task
        except asyncio.CancelledError:
            print("SME task was cancelled")
            logger.info("SME task was cancelled")
    
    # Cancel the Equities task if it's still running
    if equities_task and not equities_task.done():
        equities_task.cancel()
        try:
            await equities_task
        except asyncio.CancelledError:
            print("Equities task was cancelled")
            logger.info("Equities task was cancelled")

@app.get("/")
async def home():
    return "New automation method Trillionaire"

@app.get("/status")
async def status():
    global sme_task, equities_task
    return {
        "sme_task_running": sme_task is not None and not sme_task.done(),
        "equities_task_running": equities_task is not None and not equities_task.done()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",port=5000)
