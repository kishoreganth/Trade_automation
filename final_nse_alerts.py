import requests
import gzip
import brotli
import json
import pandas as pd
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
import threading
import schedule
import time
from pydantic import BaseModel
import csv
from stock_info import companie_names
from fastapi.middleware.cors import CORSMiddleware

# Base URL to fetch cookies
base_url = "https://www.nseindia.com"
api_url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
# Set headers for the initial request
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
# Path to your CSV file
csv_file_path = "all_corporate_announcements.csv"
watchlist_CA_files = "watchlist_corporate_announcements.csv"

TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = "https://32f4-106-219-183-82.ngrok-free.app/webhook"  # Make sure the path matches Flask's route

chat_ids = ["776062518", "@test_kishore_ai_chat"]
chat_id = "@test_kishore_ai_chat"

global session 
session = requests.Session()
response = session.get(base_url, headers=headers)


app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request body schema for incoming webhook
class TelegramWebhook(BaseModel):
    update_id: int
    message: dict

def search_csv(keyword):
    # List to store results
    results = []

    # Open the CSV file
    with open(csv_file_path, mode="r", encoding="utf-8") as file:
        reader = csv.reader(file)

        # Iterate through rows and keep track of row index
        for row_index, row in enumerate(reader, start=1):  # Start row_index from 1 (Excel-like indexing)
            for col_index, cell in enumerate(row, start=1):  # Start col_index from 1
                if keyword.lower() in str(cell).lower():
                    # results.append((row_index, col_index, cell))
                    results.append({
                        # "row_index": row_index,
                        "row": row,
                    })

    # Return results
    return results


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
    


# def send_menu(chat_id):
#     # Define the menu options using InlineKeyboardMarkup
#     menu = {
#         "inline_keyboard": [
#             [{"text": "Option 1", "callback_data": "option_1"}],
#             [{"text": "Option 2", "callback_data": "option_2"}],
#             [{"text": "Option 3", "callback_data": "option_3"}],
#         ]
#     }

#     # Define the message payload
#     payload = {
#         "chat_id": chat_id,
#         "text": "Please choose an option:",
#         "reply_markup": json.dumps(menu),
#     }

#     # Send the request to Telegram
#     response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
#     if response.status_code == 200:
#         print("Menu sent successfully!")
#     else:
#         print(f"Failed to send menu: {response.text}")


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



#### 
##  BElow are the functino to fetch from the API every 10 seconds and send trigger in telegram based on announcement equities 
####

def get_cookies():
    # Create a session to handle cookies and headers
    global session 
    session = requests.Session()

    # Step 1: Get cookies by visiting the main site
    response = session.get(base_url, headers=headers)
    if response.status_code == 200:
        print("Cookies obtained successfully.")
    
    return session

def trigger_test_message(chat_idd, message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_idd,
        "text": message,
        "parse_mode": "HTML"
    }
    r = requests.post(url, json=payload)

def trigger_message(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    r = requests.post(url, json=payload)
    # print(r.json())

def get_CA_equities():
    global session
    if not session:
        print("SESSION need to refresh it")
        session = get_cookies()
    # print(session)
    print(" --------------------------------------- ")
    api_response = session.get(api_url, headers=headers)

    if api_response.status_code == 200:
        encoding = api_response.headers.get('Content-Encoding', '')
        try:
            if 'gzip' in encoding:
                content = gzip.decompress(api_response.content).decode('utf-8')
            elif 'br' in encoding:
                try:
                    content = brotli.decompress(api_response.content).decode('utf-8')
                except brotli.error:
                    # print("Skipping Brotli decompression due to error.")
                    content = api_response.content.decode('utf-8', errors='ignore')
            else:
                content = api_response.content.decode('utf-8')

            json_data = json.loads(content)

            if os.path.exists(csv_file_path):
                # print(f"File '{csv_file_path}' exists. Loading data...")
                df1 = pd.read_csv(csv_file_path, dtype='object')
                df2 = pd.DataFrame(json_data)
                df2.to_csv("temp.csv", index = False)

                api_df = pd.read_csv("temp.csv", dtype= 'object')

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
                        # print("DATAATATATTTTTTTTTT")
                        # print(symbol)
                        # print(sm_name)
                        # print(desc)
                        # print(attached_file)
                        # print(attached_text)
                        print("SUYMBOL IS  - ", symbol)
                        message = f"""<b>{symbol} - {sm_name}</b>\n\n{desc}\n\n<i>{attached_text}</i>\n\n<b>File:</b>\n{attached_file}"""
                        trigger_test_message("@trade_mvd",message)
                        if sm_name in companie_names:
                            # await send_message(chat_id, final_message)
                            trigger_message(message)
                            if os.path.exists(watchlist_CA_files):
                                print(f"File '{watchlist_CA_files}' exists. Loading data...")
                                new_rows.to_csv(watchlist_CA_files, mode='a', index=False)
                            else:
                                # Create a new file and write data
                                new_rows.to_csv(watchlist_CA_files, index=False)
                                print(f"New file created at {watchlist_CA_files} and data written.")

                    df1_updated = pd.concat([new_rows, df1], ignore_index=True).drop_duplicates()
                    df1_updated.to_csv(csv_file_path, index=False)
            else:
                print(f"File '{csv_file_path}' does not exist. Creating a new DataFrame.")
                # Step 2: Convert JSON to DataFrame
                df = pd.DataFrame(json_data)
                # Step 3: Save to CSV
                df.to_csv(csv_file_path, index=False)

                
        except Exception as e:
            print("Error processing the response content:")
            print(e)

    else:
        print(f"Failed to fetch API data. Status code: {api_response.status_code}")
        print(api_response.text)



def run_scheduler():
    """
    Run the scheduler in a separate thread.
    """
    schedule.every(10).seconds.do(get_CA_equities)
    print("Scheduler started.")

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    # Set the webhook
    set_webhook()
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    # Run the web server
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)