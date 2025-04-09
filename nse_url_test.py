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

from stock_info import SME_companies, BSE_NSE_companies


## TELEGRAM SETUP
TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = "https://c690-49-206-10-151.ngrok-free.app/webhook"  # Make sure the path matches Flask's route
chat_ids = ["776062518", "@test_kishore_ai_chat"]
# chat_id = "@test_kishore_ai_chat"

equity_url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
sme_url = "https://www.nseindia.com/api/corporate-announcements?index=sme"

api_url = sme_url 



app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
import logging

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

csv_file_path = "files/all_corporate_announcements.csv"
watchlist_CA_files = "files/watchlist_corporate_announcements.csv"
# chat_id = "@test_kishore_ai_chat"
TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"





gsheet_chats = "1v35Bq76X3_gA00uZan5wa0TOP60F-AHJVSCeHCPadD0"

sheet_id = gsheet_chats
gsheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
df = pd.read_csv(gsheet_url)

watchlist_chat_ids = []

for index, row in df.iterrows():
    print("row is - ", row)
    chat_id = "@" + str(row['chat_id'])
    print("CHAT ID IS - ", chat_id)
    watchlist_chat_ids.append(chat_id)

print("WATCHLIST CHAT IDS ARE - ", watchlist_chat_ids)


async def send_message(chat_id: int, text: str):
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
            print(f"Message sent to {chat_id}: {text}")
        except httpx.RequestError as e:
            print(f"Error sending message: {e}")


def set_webhook():
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


def search_csv(keyword):
    # List to store results
    results = []
    keyword = keyword.lower()

    # Open the CSV file
    with open(watchlist_CA_files, mode="r", encoding="utf-8") as file:
        reader = csv.reader(file)

        # Iterate through rows
        for row in reader:
            # Check if keyword exists in any cell of the row
            if any(keyword in str(cell).lower() for cell in row):
                results.append({
                    "row": row,
                })

    # Return results
    return results




def trigger_message(message):
    print("WATCHLIST stocks are sending to telegram")
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

def trigger_test_message(chat_idd, message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_idd,
        "text": message,
        "parse_mode": "HTML"
    }
    logger.info(f"Triggered test message: {message}")

    r = requests.post(url, json=payload)


async def response_file_handle(api_response : httpx.Response):
        
    api_response = api_response.json()
    logging.info(" FILE handling start ")
    if os.path.exists(csv_file_path):
        # print(f"File '{csv_file_path}' exists. Loading data...")
        df1 = pd.read_csv(csv_file_path, dtype='object')
        df2 = pd.DataFrame(api_response)
        df2.to_csv("files/temp.csv", index = False)

        api_df = pd.read_csv("files/temp.csv", dtype= 'object')

        # Convert all columns to the same type (e.g., to string) for comparison
        df1 = df1.map(str)
        api_df = api_df.map(str)

        # Remove extra spaces
        df1 = df1.map(lambda x: x.strip() if isinstance(x, str) else x)
        api_df = api_df.map(lambda x: x.strip() if isinstance(x, str) else x)

        # Perform an outer merge on all columns to find the differences
        merged = pd.merge(df1, api_df, how='outer', indicator=True)
        merged = merged.sort_values(by='an_dt', ascending= False)
        # print(" MERGED TABLE ")
        # print(merged)

        # # Filter rows that are only in df2 and not in df1
        new_rows = merged[merged['_merge'] == 'right_only'].drop('_merge', axis=1)
        # # Print the new rows
        print(new_rows)
        print(len(new_rows))

        if len(new_rows) > 0:
            for index, row in new_rows.iterrows():
                # job(1, "NEW RECORD OR CA")
                symbol = row["symbol"]
                sm_name = row["sm_name"]
                desc = row["desc"]
                attached_text = row["attchmntText"]
                attached_file = row["attchmntFile"]

                print("SUYMBOL IS  - ", symbol)
                message = f"""<b>{symbol} - {sm_name}</b>\n\n{desc}\n\n<i>{attached_text}</i>\n\n<b>File:</b>\n{attached_file}"""
                trigger_test_message("@trade_mvd",message)
                if sm_name in SME_companies:
                    # await send_message(chat_id, final_message)
                    trigger_message(message)
                    if os.path.exists(watchlist_CA_files):
                        print(f"File '{watchlist_CA_files}' exists. Loading data...")
                        logging.info(f"File '{watchlist_CA_files}' exists. Loading data...")

                        new_rows.to_csv(watchlist_CA_files, mode='a', index=False)
                    else:
                        # Create a new file and write data
                        new_rows.to_csv(watchlist_CA_files, index=False)
                        print(f"New file created at {watchlist_CA_files} and data written.")
                        logging.info(f"New file created at {watchlist_CA_files} and data written.")

            df1_updated = pd.concat([new_rows, df1], ignore_index=True).drop_duplicates()
            df1_updated.to_csv(csv_file_path, index=False)
    else:
        print(f"File '{csv_file_path}' does not exist. Creating a new DataFrame.")
        logging.info(f"File '{csv_file_path}' does not exist. Creating a new DataFrame.")

        # Step 2: Convert JSON to DataFrame
        df = pd.DataFrame(api_response)
        # Step 3: Save to CSV
        df.to_csv(csv_file_path, index=False)

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

        ca_docs = nsefetch(api_url)
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
                response = await client.get(api_url, headers=headers)
                
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
        await asyncio.sleep(30)
        return None

async def process_ca_data(ca_docs):
    """Process the corporate announcements data and update CSV files"""
    if os.path.exists(csv_file_path):
        logger.info(f"Processing existing file: {csv_file_path}")
        df1 = pd.read_csv(csv_file_path, dtype='object')
        df2 = pd.DataFrame(ca_docs)
        df2.to_csv("files/temp.csv", index=False)
        
        api_df = pd.read_csv("files/temp.csv", dtype='object')
        
        # Convert all columns to string and strip whitespace
        df1 = df1.map(str).map(lambda x: x.strip() if isinstance(x, str) else x)
        api_df = api_df.map(str).map(lambda x: x.strip() if isinstance(x, str) else x)
        
        # Find new rows
        merged = pd.merge(df1, api_df, how='outer', indicator=True)
        merged = merged.sort_values(by='an_dt', ascending=False)
        new_rows = merged[merged['_merge'] == 'right_only'].drop('_merge', axis=1)
        
        if len(new_rows) > 0:
            for index, row in new_rows.iterrows():
                symbol = row["symbol"]
                sm_name = row["sm_name"]
                desc = row["desc"]
                attached_text = row["attchmntText"]
                attached_file = row["attchmntFile"]
                
                message = f"""<b>{symbol} - {sm_name}</b>\n\n{desc}\n\n<i>{attached_text}</i>\n\n<b>File:</b>\n{attached_file}"""
                trigger_test_message("@trade_mvd", message)
                
                if sm_name in SME_companies:
                    trigger_message(message)
                    update_watchlist_file(new_rows)
            
            # Update main CSV file
            df1_updated = pd.concat([new_rows, df1], ignore_index=True).drop_duplicates()
            df1_updated.to_csv(csv_file_path, index=False)
            
        return 1
    else:
        logger.info(f"Creating new file: {csv_file_path}")
        df = pd.DataFrame(ca_docs)
        df.to_csv(csv_file_path, index=False)
        return 1

def update_watchlist_file(new_rows):
    """Update the watchlist CSV file with new rows"""
    if os.path.exists(watchlist_CA_files):
        logger.info(f"Appending to existing watchlist file: {watchlist_CA_files}")
        new_rows.to_csv(watchlist_CA_files, mode='a', index=False)
    else:
        logger.info(f"Creating new watchlist file: {watchlist_CA_files}")
        new_rows.to_csv(watchlist_CA_files, index=False)




## THIS IS to get input message for the AI bot in the telegram, I response based on the previous data 
@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        print(f"Incoming data: {data}")  # Log data for debugging
        print(data)
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")

            if text:
                # Respond to the user
                ## search from the existing files of equity
                results = search_csv(text)
                print(results)
                print(type(results))
                if len(results) > 0:
                    for i in range(len(results)):
                        print(results[i])
                        symbol = results[i]["row"][0]
                        sm_name = results[i]["row"][4]
                        desc = results[i]["row"][1]
                        attached_text = results[i]["row"][11]
                        attached_file = results[i]["row"][3]

                        final_message = f"""<b>{symbol} - {sm_name}</b>\n\n{desc}\n\n<i>{attached_text}</i>\n\n<b>File:</b>\n{attached_file}"""
                        await send_message(chat_id, final_message)

            else:
                await send_message(chat_id, "I can only process text messages right now.")

        return {"status": "ok"}
    except Exception as e:
        print(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")



# Function to run the periodic task
async def run_periodic_task():
    logger.info("starting thescript ")
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
            logger.error(f"Error in run_periodic_task: {str(e)}")
            logger.info("Error occurred, waiting 30 seconds before retrying...")
            await asyncio.sleep(30)  # Wait for 60 seconds before retrying


# Start the background task when FastAPI is running
@app.get("/start-scheduler/")
async def start_scheduler(background_tasks: BackgroundTasks):
    set_webhook()
    background_tasks.add_task(run_periodic_task)
    return {"message": "Scheduler started!"}

@app.get("/")
async def home():
    return "New automation method Trillionaire"



if __name__ == "__main__":

    import uvicorn
    uvicorn.run(app, host="0.0.0.0",port=5000)
