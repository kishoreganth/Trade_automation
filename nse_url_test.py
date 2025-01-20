from nsepython import *
import asyncio

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from stock_info import companie_names


app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

csv_file_path = "files/all_corporate_announcements.csv"
watchlist_CA_files = "files/watchlist_corporate_announcements.csv"
chat_id = "@test_kishore_ai_chat"
TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"


def trigger_message(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    r = requests.post(url, json=payload)
    # print(r.json())

def trigger_test_message(chat_idd, message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_idd,
        "text": message,
        "parse_mode": "HTML"
    }
    r = requests.post(url, json=payload)

async def CA_equities():
    # positions = nsefetch('https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O')
    ca_docs = nsefetch('https://www.nseindia.com/api/corporate-announcements?index=equities')
    # print(ca_docs)
    print(type(ca_docs))

    if os.path.exists(csv_file_path):
        # print(f"File '{csv_file_path}' exists. Loading data...")
        df1 = pd.read_csv(csv_file_path, dtype='object')
        df2 = pd.DataFrame(ca_docs)
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

        # # Filter rows that are only in df2 and not in df1
        new_rows = merged[merged['_merge'] == 'right_only'].drop('_merge', axis=1)
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
                print("DATAATATATTTTTTTTTT")
                print(symbol)
                print(sm_name)
                print(desc)
                print(attached_file)
                print(attached_text)
                print("SUYMBOL IS  - ", symbol)
                message = f"""<b>{symbol} - {sm_name}</b>\n\n{desc}\n\n<i>{attached_text}</i>\n\n<b>File:</b>\n{attached_file}"""
                trigger_test_message("@trade_mvd",message)
                if sm_name in companie_names:
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


# CA_equities()

# Function to run the periodic task
async def run_periodic_task():
    while True:
        logging.info("starting")
        await CA_equities()  # Run the task
        logging.info("next loop")

        await asyncio.sleep(10)  # Wait for 10 seconds before running it again


# Start the background task when FastAPI is running
@app.get("/start-scheduler/")
async def start_scheduler(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_periodic_task)
    return {"message": "Scheduler started!"}


if __name__ == "__main__":

    import uvicorn
    uvicorn.run(app, host="0.0.0.0",port=5000)
