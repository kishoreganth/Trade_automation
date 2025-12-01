from nsepython import *
import asyncio
# import nsepythonserver
import csv
import requests
import os
import json
import pandas as pd
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
import pyotp
import secrets
import sqlite3
import aiosqlite
import hashlib
from starlette.middleware.sessions import SessionMiddleware
import httpx
import aiofiles
import aiofiles.os
import io
from contextlib import asynccontextmanager
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import pytz  # For timezone handling
import aiohttp
import time
import psutil
import gc
import tempfile
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
# from fpdf import FPDF
import sys
import codecs
from stock_info import SME_companies, BSE_NSE_companies
from async_ocr_from_image import main_ocr_async, pdf_to_png_async, process_ocr_from_images_async, encode_images_async, analyze_financial_metrics_async, get_global_ocr_model
from neo_main_login import main as neo_main_login
from place_order import main as place_order_main
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


from get_quote import main as get_quote_main
import uuid
from dataclasses import dataclass, asdict, field as dataclass_field

# Set up logging to both file and console
logger = logging.getLogger()    
logger.setLevel(logging.INFO)

# ============================================================================
# JOB STATUS TRACKING SYSTEM
# ============================================================================

@dataclass
class JobStatus:
    """Track status of long-running background jobs"""
    job_id: str
    type: str  # "get_quotes", "place_order", "ai_analyze"
    status: str  # "running", "completed", "failed"
    progress: int  # 0-100
    message: str
    started_at: str
    completed_at: Optional[str] = None
    result: Optional[Dict] = None
    error: Optional[str] = None

# In-memory job store (use DB for persistence across restarts)
active_jobs: Dict[str, JobStatus] = {}

# ============================================================================
# END JOB STATUS TRACKING
# ============================================================================

# Indian Standard Time timezone
IST = pytz.timezone('Asia/Kolkata')

def get_ist_now():
    """Get current time in IST timezone"""
    return datetime.now(IST)

# Cleanup configuration
CLEANUP_CONFIG = {
    "pdf_retention_days": 30,      # Keep PDFs for 30 days
    "images_retention_days": 7,     # Keep images for 7 days (shorter since they're larger)
    "cleanup_interval_hours": 24,   # Run cleanup every 24 hours
    "post_ocr_cleanup": True,       # Delete images immediately after OCR completes
    "folders": {
        "pdf": "files/pdf",
        "images": "images",
        "downloads": "downloads",
        "temp_uploads": "temp_uploads"
    }
}



# Add this near the top with other global variables
BASE_URL = "http://122.165.113.41:5000"  # Can be changed to any domain/IP
# BASE_URL = "http://localhost:5000"
## TELEGRAM SETUP
TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = f"{BASE_URL}/webhook"  # Updated to use BASE_URL
chat_ids = ["776062518", "@test_kishore_ai_chat"]
# chat_id = "@test_kishore_ai_chat"

equity_url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
sme_url = "https://www.nseindia.com/api/corporate-announcements?index=sme"


# Known tags we care about
fields = [
    # Existing fields
    "NSESymbol", "NameOfTheCompany", "ReasonOfChange", "Designation",
    "NameOfThePersonOrAuditorOrAuditFirmOrRTA",
    "EffectiveDateOfAppointmentOrResignationOrRemovalOrDisqualificationOrCessationOrVacationOfOfficeDueToStatutoryAuthorityOrderOrAdditionalChargeOrChangeInDesignation",
    "TermOfAppointment", "BriefProfile", "RemarksForWebsiteDissemination",
    "TypeOfAnnouncementPertainingToRegulation30Restructuring",
    "EventOfAnnouncementPertainingToRegulation30Restructuring",
    "DateOfEventOfAnnouncementPertainingToRegulation30Restructuring",
    "NameOfAcquirer", "RelationshipOfAcquirerWithTheListedEntity",
    "DetailsOfOtherRelationWithTheListedEntity", "NameOfTheTargetEntity",
    "TurnoverOfTargetEntity", "ProfitAfterTaxOfTargetEntity",
    "NetWorthOfTargetEntity",
    "WhetherTheAcquisitionWouldFallWithinRelatedPartyTransactions",
    "WhetherAcquisitionEventRPTIsMaterial",
    "ObjectsAndEffectsOfAcquisitionIncludingButNotLimitedToDisclosureOfReasonsForAcquisitionOfTargetEntityIfItsBusinessIsOutsideTheMainLineOfBusinessOfTheListedEntity",
    "DisclosureOfRelationshipsBetweenDirectorsInCaseOfAppointmentOfDirector",
    "IndustryToWhichTheEntityBeingAcquiredBelongs",
    "CountryInWhichTheAcquiredEntityHasPresence",
    "DateOfBoardMeetingInWhichRPTApprovalTakenForAcquisitionEvent",
    "DateOfAuditCommitteeMeetingInWhichRPTApprovalTakenForAcquisitionEvent",
    "WhetherThePromoterOrPromoterGroupOrGroupOrAssociateOrHoldingOrSubsidiaryCompaniesOrDirectorAndKMPAndItsRelativesHaveAnyInterestInTheEntityBeingAcquired",
    "WhetherAcquisitionIsDoneAtArmsLength",
    "WhetherAnyGovernmentalOrRegulatoryApprovalsRequiredForTheAcquisition",
    "WhetherTheAcquisitionTransactionWillBeInTranches",
    "IndicativeTimePeriodForCompletionOfTheAcquisition",
    "NatureOfConsiderationForAcquisitionEvent",
    "CostOfAcquisitionOrThePriceAtWhichTheSharesAreAcquired",
    "ExistingPercentageOfShareholdingHeldByAcquirer",
    "BriefBackgroundAboutTheEntityAcquiredInTermsOfProductsLineOfBusinessAcquired",
    "StartYearOfFirstPreviousYear", "EndYearOfFirstPreviousYear",
    "TurnoverOfFirstPreviousYear", "PANOfDesignatedPerson",

    # New fields from XML7
    "ISIN", "TypeOfAnnouncement", "TypeOfEvent", "DateOfOccurrenceOfEvent",
    "TimeOfOccurrenceOfEvent", "DateOfReport",
    "DateOfBoardMeetingForApprovalOfIssuanceOfSecurityForAllotmentOfSecurities",
    "WhetherAnyDisclosureWasMadeForTheIssuanceOfSecuritiesAsPerSEBILODRAndCircular9ThSeptember2015ForAllotmentOfSecurities",
    "ReasonsForNonDisclosureForTheIssuanceOfSecuritiesAsPerSEBILODRAndCircular9ThSeptember2015ForAllotmentOfSecurities",
    "DateOfBoardOrCommitteeForAllotmentOfSecurities",
    "TypeOfSecuritiesAllottedForAllotmentOfSecurities",
    "TypeOfIssuanceForAllotmentOfSecurities",
    "PaidUpShareCapitalPreAllotmentOfSecurities",
    "NumberOfSharesPaidUpPreAllotmentOfSecurities",
    "PaidUpShareCapitalPostAllotmentOfSecurities",
    "NumberOfSharesPaidUpPostAllotmentOfSecurities"
]

#### WATCH LIST CHATID FROM GOOGLE SHEET

gsheet_chats = "1v35Bq76X3_gA00uZan5wa0TOP60F-AHJVSCeHCPadD0"
sheet_id = gsheet_chats
watchlist_sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"

# Initialize empty list - will be populated async during startup
watchlist_chat_ids = []

async def load_watchlist_chat_ids():
    """Load watchlist chat IDs from Google Sheets asynchronously"""
    global watchlist_chat_ids
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(watchlist_sheet_url)
            response.raise_for_status()
            
            df = pd.read_csv(io.StringIO(response.text))
            print("Watchlist DataFrame loaded:", df)
            
            watchlist_chat_ids = []
            for index, row in df.iterrows():
                print("row is - ", row)
                chat_id = "@" + str(row['Telegram link'])
                print("CHAT ID IS - ", chat_id)
                watchlist_chat_ids.append(chat_id)
            
            print("WATCHLIST CHAT IDS ARE - ", watchlist_chat_ids)
            logger.info(f"Loaded {len(watchlist_chat_ids)} watchlist chat IDs")
            
    except Exception as e:
        logger.error(f"Error loading watchlist chat IDs: {e}")
        watchlist_chat_ids = []  # Fallback to empty list

#######################

# ============================================================================
# CLEANUP SYSTEM - Efficient, Async, Scalable File Management
# ============================================================================

async def cleanup_old_files_async(folder_path: str, retention_days: int) -> Dict[str, int]:
    """
    Async cleanup of files older than retention_days.
    Returns statistics about cleanup operation.
    """
    stats = {
        "files_deleted": 0,
        "space_freed_mb": 0,
        "errors": 0
    }
    
    try:
        folder = Path(folder_path)
        if not folder.exists():
            logger.info(f"📁 Folder {folder_path} doesn't exist, skipping cleanup")
            return stats
        
        cutoff_time = get_ist_now() - timedelta(days=retention_days)
        cutoff_timestamp = cutoff_time.timestamp()
        
        logger.info(f"🧹 Starting cleanup in {folder_path} (files older than {retention_days} days)")
        
        # Walk through directory recursively
        for item in folder.rglob('*'):
            if item.is_file():
                try:
                    # Check file modification time
                    file_mtime = item.stat().st_mtime
                    
                    if file_mtime < cutoff_timestamp:
                        # Get file size before deletion
                        file_size = item.stat().st_size
                        
                        # Delete file asynchronously
                        await asyncio.to_thread(item.unlink)
                        
                        stats["files_deleted"] += 1
                        stats["space_freed_mb"] += file_size / (1024 * 1024)
                        
                        logger.debug(f"🗑️  Deleted: {item.name} ({file_size / 1024:.1f} KB)")
                        
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"❌ Error deleting {item}: {e}")
        
        # Clean up empty directories
        for item in sorted(folder.rglob('*'), reverse=True):
            if item.is_dir() and not any(item.iterdir()):
                try:
                    await asyncio.to_thread(item.rmdir)
                    logger.debug(f"📂 Removed empty directory: {item.name}")
                except Exception as e:
                    logger.debug(f"Could not remove directory {item}: {e}")
        
        logger.info(
            f"✅ Cleanup complete for {folder_path}: "
            f"{stats['files_deleted']} files deleted, "
            f"{stats['space_freed_mb']:.2f} MB freed"
        )
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup of {folder_path}: {e}")
        stats["errors"] += 1
    
    return stats


async def cleanup_specific_folder_async(folder_path: str) -> Dict[str, int]:
    """
    Delete entire folder and its contents immediately (post-processing cleanup).
    Returns statistics about cleanup operation.
    """
    stats = {
        "files_deleted": 0,
        "space_freed_mb": 0,
        "errors": 0
    }
    
    try:
        folder = Path(folder_path)
        if not folder.exists():
            return stats
        
        # Calculate total size before deletion
        total_size = 0
        file_count = 0
        
        for item in folder.rglob('*'):
            if item.is_file():
                total_size += item.stat().st_size
                file_count += 1
        
        # Delete entire folder asynchronously
        await asyncio.to_thread(shutil.rmtree, folder_path, ignore_errors=True)
        
        stats["files_deleted"] = file_count
        stats["space_freed_mb"] = total_size / (1024 * 1024)
        
        logger.info(
            f"🗑️  Post-OCR cleanup: Deleted {folder_path} "
            f"({file_count} files, {stats['space_freed_mb']:.2f} MB freed)"
        )
        
    except Exception as e:
        logger.error(f"❌ Error during post-processing cleanup of {folder_path}: {e}")
        stats["errors"] += 1
    
    return stats


async def run_periodic_cleanup():
    """
    Background task that runs cleanup periodically based on retention policies.
    Runs every 24 hours by default.
    """
    interval_seconds = CLEANUP_CONFIG["cleanup_interval_hours"] * 3600
    
    while True:
        try:
            logger.info("🕐 Starting periodic cleanup task...")
            
            total_stats = {
                "files_deleted": 0,
                "space_freed_mb": 0,
                "errors": 0
            }
            
            # Cleanup PDFs older than 30 days
            pdf_stats = await cleanup_old_files_async(
                CLEANUP_CONFIG["folders"]["pdf"],
                CLEANUP_CONFIG["pdf_retention_days"]
            )
            
            # Cleanup images older than 7 days
            images_stats = await cleanup_old_files_async(
                CLEANUP_CONFIG["folders"]["images"],
                CLEANUP_CONFIG["images_retention_days"]
            )
            
            # Cleanup downloads older than 30 days
            downloads_stats = await cleanup_old_files_async(
                CLEANUP_CONFIG["folders"]["downloads"],
                CLEANUP_CONFIG["pdf_retention_days"]
            )
            
            # Cleanup temp uploads older than 1 day
            temp_stats = await cleanup_old_files_async(
                CLEANUP_CONFIG["folders"]["temp_uploads"],
                1  # Keep temp files for only 1 day
            )
            
            # Aggregate statistics
            for stats in [pdf_stats, images_stats, downloads_stats, temp_stats]:
                total_stats["files_deleted"] += stats["files_deleted"]
                total_stats["space_freed_mb"] += stats["space_freed_mb"]
                total_stats["errors"] += stats["errors"]
            
            logger.info(
                f"✅ Periodic cleanup completed: "
                f"{total_stats['files_deleted']} total files deleted, "
                f"{total_stats['space_freed_mb']:.2f} MB freed, "
                f"{total_stats['errors']} errors"
            )
            
            # Force garbage collection after cleanup
            gc.collect()
            
        except Exception as e:
            logger.error(f"❌ Error in periodic cleanup task: {e}")
        
        # Wait for next cleanup cycle
        await asyncio.sleep(interval_seconds)


async def post_ocr_cleanup_async(image_folder: str):
    """
    Cleanup images immediately after OCR processing completes.
    Called after successful OCR analysis.
    """
    if not CLEANUP_CONFIG["post_ocr_cleanup"]:
        return
    
    try:
        stats = await cleanup_specific_folder_async(image_folder)
        logger.info(f"✅ Post-OCR cleanup: {stats['files_deleted']} files, {stats['space_freed_mb']:.2f} MB freed")
    except Exception as e:
        logger.error(f"❌ Post-OCR cleanup failed for {image_folder}: {e}")

# ============================================================================
# END CLEANUP SYSTEM
# ============================================================================
    
# Start the background tasks when the application starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application startup and shutdown events"""
    global sme_task, equities_task, cleanup_task
    
    # Startup: Create directories and start background tasks
    os.makedirs("files/pdf", exist_ok=True)
    os.makedirs(CLEANUP_CONFIG["folders"]["images"], exist_ok=True)
    os.makedirs(CLEANUP_CONFIG["folders"]["downloads"], exist_ok=True)
    os.makedirs(CLEANUP_CONFIG["folders"]["temp_uploads"], exist_ok=True)
    
    # Initialize database
    await init_db()
    logger.info("Dashboard database initialized")
    
    # Load Google Sheets data asynchronously during startup
    logger.info("Loading Google Sheets data...")
    await asyncio.gather(
        load_watchlist_chat_ids(),
        load_result_concall_keywords()
    )
    logger.info("Google Sheets data loaded successfully")
    
    # Pre-load OCR model at startup for 80% speed improvement
    logger.info("🔥 Pre-loading OCR model for global caching...")
    start_model_time = time.time()
    await get_global_ocr_model()
    model_load_time = time.time() - start_model_time
    logger.info(f"✅ OCR model pre-loaded and cached in {model_load_time:.2f}s - All future requests will be 80% faster!")
    
    # Start all background tasks in parallel using asyncio.create_task
    # sme_task = asyncio.create_task(run_periodic_task_sme())
    equities_task = asyncio.create_task(run_periodic_task_equities())
    cleanup_task = asyncio.create_task(run_periodic_cleanup())
    
    logger.info("✅ All background tasks started: Equities and Periodic Cleanup (24h interval)")
    logger.info(f"🧹 Cleanup policy: PDFs={CLEANUP_CONFIG['pdf_retention_days']}d, Images={CLEANUP_CONFIG['images_retention_days']}d, Post-OCR cleanup={'ON' if CLEANUP_CONFIG['post_ocr_cleanup'] else 'OFF'}")
    
    yield  # FastAPI will run the application here
    
    # Shutdown: Clean up tasks
    if sme_task and not sme_task.done():
        sme_task.cancel()
        try:
            await sme_task
        except asyncio.CancelledError:
            print("SME task was cancelled")
            logger.info("SME task was cancelled")
    
    if equities_task and not equities_task.done():
        equities_task.cancel()
        try:
            await equities_task
        except asyncio.CancelledError:
            print("Equities task was cancelled")
            logger.info("Equities task was cancelled")
    
# Create the FastAPI app with lifespan
app = FastAPI(lifespan=lifespan)

# Add session middleware for authentication
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure directories exist and have proper permissions
os.makedirs("files", exist_ok=True)
os.makedirs("files/pdf", exist_ok=True)

# Log the absolute paths for debugging
files_dir = os.path.abspath("files")
pdf_dir = os.path.abspath("files/pdf")
logger.info(f"Files directory: {files_dir}")
logger.info(f"PDF directory: {pdf_dir}")

# Verify directory permissions
logger.info(f"Files directory exists: {os.path.exists(files_dir)}")
logger.info(f"PDF directory exists: {os.path.exists(pdf_dir)}")
logger.info(f"Files directory permissions: {oct(os.stat(files_dir).st_mode)[-3:]}")
logger.info(f"PDF directory permissions: {oct(os.stat(pdf_dir).st_mode)[-3:]}")

# Mount static files for serving PDFs with explicit directory path and HTML listing enabled
app.mount("/files", StaticFiles(directory=files_dir, html=True, check_dir=True), name="files")

# Mount static files for dashboard
app.mount("/static", StaticFiles(directory="static"), name="static")

# Database setup for dashboard - use environment variable for Docker persistence
DB_PATH = os.getenv('DB_PATH', 'messages.db')

class MessageData(BaseModel):
    chat_id: str
    message: str
    timestamp: Optional[str] = None
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    description: Optional[str] = None
    file_url: Optional[str] = None
    option: Optional[str] = None

class TOTPRequest(BaseModel):
    totp_code: str

class OrderRequest(BaseModel):
    symbol: str
    quantity: int
    price: float
    order_type: str

class LoginRequest(BaseModel):
    username: str
    password: str

class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast_message(self, message: dict):
        """Broadcast message to all connected clients"""
        if self.active_connections:
            logger.info(f"Broadcasting to {len(self.active_connections)} connections")
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending to WebSocket: {e}")
                    disconnected.append(connection)
            
            # Remove disconnected clients
            for conn in disconnected:
                self.disconnect(conn)

# WebSocket manager instance
ws_manager = WebSocketManager()

async def init_db():
    """Initialize SQLite database with migration support"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Create table with basic structure first
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                symbol TEXT,
                company_name TEXT,
                description TEXT,
                file_url TEXT,
                raw_message TEXT
            )
        """)
        
        # Create financial metrics table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS financial_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                year TEXT NOT NULL,
                revenue REAL,
                pbt REAL,
                pat REAL,
                total_income REAL,
                other_income REAL,
                eps REAL,
                reported_at TEXT NOT NULL,
                message_id INTEGER,
                FOREIGN KEY (message_id) REFERENCES messages (id)
            )
        """)
        
        # Create users table for authentication
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        """)
        
        # Create sessions table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_token TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        # Check if option column exists, if not add it
        cursor = await db.execute("PRAGMA table_info(messages)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'option' not in column_names:
            logger.info("Adding option column to existing database")
            await db.execute("ALTER TABLE messages ADD COLUMN option TEXT")
        
        # Create default admin user if no users exist
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        user_count = (await cursor.fetchone())[0]
        
        if user_count == 0:
            # Default credentials: admin / admin123
            default_username = "admin"
            default_password = "admin123"
            password_hash = hashlib.sha256(default_password.encode()).hexdigest()
            
            await db.execute("""
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
            """, (default_username, password_hash, get_ist_now().isoformat()))
            
            logger.info(f"Created default admin user - Username: {default_username}, Password: {default_password}")
        
        await db.commit()
    logger.info("Database initialized with authentication tables")

def parse_message_content(message: str) -> Dict:
    """Parse the HTML message to extract structured data"""
    try:
        # Extract symbol and company name from the message
        lines = message.split('\n')
        
        # First line usually contains symbol and company name
        first_line = lines[0].replace('<b>', '').replace('</b>', '') if lines else ""
        
        symbol = ""
        company_name = ""
        description = ""
        file_url = ""
        
        # Parse first line for symbol and company name
        if ' - ' in first_line:
            parts = first_line.split(' - ')
            if len(parts) >= 3:
                symbol = parts[1].strip()
                company_name = parts[2].strip()
        
        # Extract description (usually the middle part)
        desc_lines = []
        for line in lines[1:]:
            if line.strip() and not line.startswith('<a href=') and 'File:' not in line:
                clean_line = line.replace('<i>', '').replace('</i>', '').strip()
                if clean_line:
                    desc_lines.append(clean_line)
        
        description = '\n'.join(desc_lines)
        
        # Extract file URL
        for line in lines:
            if '<a href=' in line:
                start = line.find('href="') + 6
                end = line.find('"', start)
                if start > 5 and end > start:
                    file_url = line[start:end]
                break
        
        return {
            "symbol": symbol,
            "company_name": company_name,
            "description": description,
            "file_url": file_url
        }
    except Exception as e:
        logger.error(f"Error parsing message: {e}")
        return {"symbol": "", "company_name": "", "description": "", "file_url": ""}

# Add a test endpoint to check PDF directory
@app.get("/check_pdf_dir")
async def check_pdf_dir():
    try:
        # Get absolute paths
        abs_pdf_dir = os.path.abspath(pdf_dir)
        
        # List all files in the directory
        pdf_files = os.listdir(abs_pdf_dir)
        
        # Get detailed file info
        file_details = []
        for file in pdf_files:
            file_path = os.path.join(abs_pdf_dir, file)
            file_details.append({
                "name": file,
                "size": os.path.getsize(file_path),
                "permissions": oct(os.stat(file_path).st_mode)[-3:],
                "exists": os.path.exists(file_path),
                "is_file": os.path.isfile(file_path)
            })
        
        return {
            "pdf_dir": abs_pdf_dir,
            "exists": os.path.exists(abs_pdf_dir),
            "is_dir": os.path.isdir(abs_pdf_dir),
            "permissions": oct(os.stat(abs_pdf_dir).st_mode)[-3:],
            "files": file_details,
            "static_files_dir": files_dir,
            "mount_point": "/files"
        }
    except Exception as e:
        logger.error(f"Error in check_pdf_dir: {str(e)}")
        return {"error": str(e), "type": str(type(e))}


# File handler with UTF-8 encoding
file_handler = logging.FileHandler('app.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Console handler with UTF-8 encoding

if sys.platform == 'win32':

    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# Remove any existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Add both handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Store task references globally
sme_task = None
equities_task = None
cleanup_task = None
ai_processing_active = False  # Flag to pause background tasks during AI processing

csv_file_path = "files/all_corporate_announcements.csv"
watchlist_CA_files = "files/watchlist_corporate_announcements.csv"
# chat_id = "@test_kishore_ai_chat"
TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"

# "fundraisensebse"




# Keyword _custom group
gid = "1091746650"
keyword_custom_group_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

concall_gid = "341478113"
result_concall_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={concall_gid}"

# Initialize empty dict - will be populated async during startup
result_concall_keywords = {}

async def load_result_concall_keywords():
    """Load result concall keywords from Google Sheets asynchronously"""
    global result_concall_keywords
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(result_concall_url)
            response.raise_for_status()
            
            result_concall_df = pd.read_csv(io.StringIO(response.text))
            print("Result concall DataFrame loaded:", result_concall_df)
            
            result_concall_keywords = {}
            for index, row in result_concall_df.iterrows():
                group_id = "@" + str(row['group_id']).strip()
                keywords_str = str(row['keywords']) if pd.notna(row['keywords']) else ""
                # Split by comma and strip each keyword
                keywords = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
                result_concall_keywords[group_id] = keywords
                print("these are the result_concall id and keywords - ", result_concall_keywords)
                
            logger.info(f"Loaded result concall keywords for {len(result_concall_keywords)} groups")
            
    except Exception as e:
        logger.error(f"Error reading Google Sheet: {str(e)}")
        logger.info("Continuing without custom group keywords due to sheet being edited or unavailable")
        result_concall_keywords = {}  # Set empty dict to continue processing without custom groups

async def load_group_keywords_async():
    """Load group keywords from Google Sheets asynchronously"""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(keyword_custom_group_url)
            response.raise_for_status()
            
            group_keyword_df = pd.read_csv(io.StringIO(response.text))
            print("Group keywords DataFrame loaded:", group_keyword_df)
            
            group_id_keywords = {}
            for index, row in group_keyword_df.iterrows():
                group_id = "@" + str(row['group_id']).strip()
                keywords_str = str(row['keywords']) if pd.notna(row['keywords']) else ""
                option_str = str(row['OPTION']) if pd.notna(row['OPTION']) else ""
                
                # Split by comma and strip each keyword
                keywords = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
                
                # Store both keywords and option in the dictionary
                group_id_keywords[group_id] = {
                    'keywords': keywords,
                    'option': option_str.strip() if option_str else ""
                }
            
            print("these are the group id, keywords and options - ", group_id_keywords)
            logger.info(f"Loaded group keywords for {len(group_id_keywords)} groups")
            return group_id_keywords
            
    except Exception as e:
        logger.error(f"Error reading Google Sheet for group keywords: {str(e)}")
        logger.info("Continuing without custom group keywords due to sheet being edited or unavailable")
        return {}  # Return empty dict to continue processing without custom groups
                

async def send_webhook_message(chat_id: int, text: str):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    async with httpx.AsyncClient(follow_redirects=True) as client:
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
        async with aiofiles.open(csv_file_path, mode="r", encoding="utf-8") as file:
            content = await file.read()
            reader = csv.reader(io.StringIO(content))
            
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
    
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for chat_id in watchlist_chat_ids:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            logger.info(f"Triggered message: {message}")

            try:
                r = await client.post(url, json=payload)
                r.raise_for_status()
            except httpx.RequestError as e:
                logger.error(f"Error sending watchlist message to {chat_id}: {e}")
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error sending watchlist message to {chat_id}: {e.response.status_code}")
    # print(r.json())


# this is the test message to see if the script is working or not
# This will send all the CA docs to the trade_mvd chat id ( which is our Script CA running telegram )
async def trigger_test_message(chat_idd, message, type="test", symbol="", company_name="", description="", file_url=""):
    # Send to Telegram as before
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_idd,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False  # Allow URL previews
    }
    # logger.info(f"Triggered test message: {message}")
    print("triggered", chat_idd, "  -- message is ", message)
    
    # Use async HTTP client for non-blocking Telegram API call
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Error sending test message to {chat_idd}: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending test message to {chat_idd}: {e.response.status_code}")
    
    # Also save to local database for UI dashboard
    try:
        # Create message data with all provided fields
        message_data = MessageData(
            chat_id=chat_idd,
            message=message,
            timestamp=get_ist_now().isoformat(),
            symbol=symbol,
            company_name=company_name,
            description=description,
            file_url=file_url,
            option=type
        )
        
        # Parse message content only if fields not provided
        if not message_data.symbol or not message_data.company_name or not message_data.description or not message_data.file_url:
            parsed = parse_message_content(message_data.message)
            if not message_data.symbol:
                message_data.symbol = parsed.get("symbol", "")
            if not message_data.company_name:
                message_data.company_name = parsed.get("company_name", "")
            if not message_data.description:
                message_data.description = parsed.get("description", "")
            if not message_data.file_url:
                message_data.file_url = parsed.get("file_url", "")
        
        # Skip database save and WebSocket for test messages
        if type == "test":
            print(f"✅ Test message sent to Telegram only (not saved to DB): {message_data.symbol} - {message_data.company_name}")
            return None
        
        # Save to database (only non-test messages)
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                INSERT INTO messages 
                (chat_id, message, timestamp, symbol, company_name, description, file_url, raw_message, option)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_data.chat_id,
                message_data.message,
                message_data.timestamp,
                message_data.symbol,
                message_data.company_name,
                message_data.description,
                message_data.file_url,
                message_data.message,
                message_data.option
            ))
            message_id = cursor.lastrowid
            await db.commit()
        
        # Broadcast to WebSocket clients
        await ws_manager.broadcast_message({
            "type": "new_message",
            "message": message_data.dict()
        })
        
        print(f"✅ Message saved to dashboard database: {message_data.symbol} - {message_data.company_name}")
        
        return message_id  # Return the message ID for linking with financial metrics
        
    except Exception as e:
        # Don't let database errors break the main Telegram functionality
        print(f"⚠️ Error saving to dashboard database: {e}")
        return None

async def process_financial_metrics(financial_metrics, stock_symbol, message_id=None):
    """Process financial metrics data and store in database"""
    try:
        if not financial_metrics or 'quarterly_data' not in financial_metrics:
            logger.warning(f"No quarterly data found in financial metrics for {stock_symbol}")
            return []
            
        quarterly_data = financial_metrics.get('quarterly_data', [])
        reported_at = get_ist_now().isoformat()
        
        stored_metrics = []
        
        async with aiosqlite.connect(DB_PATH) as db:
            for quarter in quarterly_data:
                # Insert financial metrics data
                cursor = await db.execute("""
                    INSERT INTO financial_metrics 
                    (stock_symbol, period, year, revenue, pbt, pat, total_income, other_income, eps, reported_at, message_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    stock_symbol,
                    quarter.get('period', ''),
                    quarter.get('year_ended', ''),
                    quarter.get('revenue_from_operations', 0),
                    quarter.get('profit_before_tax', 0),
                    quarter.get('profit_after_tax', 0),
                    quarter.get('total_income', 0),
                    quarter.get('other_income', 0),
                    quarter.get('earnings_per_share', 0),
                    reported_at,
                    message_id
                ))
                
                # Prepare data for frontend
                metric_data = {
                    "id": cursor.lastrowid,
                    "stock_symbol": stock_symbol,
                    "period": quarter.get('period', ''),
                    "year": quarter.get('year_ended', ''),
                    "revenue": quarter.get('revenue_from_operations', 0),
                    "pbt": quarter.get('profit_before_tax', 0),
                    "pat": quarter.get('profit_after_tax', 0),
                    "total_income": quarter.get('total_income', 0),
                    "other_income": quarter.get('other_income', 0),
                    "eps": quarter.get('earnings_per_share', 0),
                    "reported_at": reported_at
                }
                stored_metrics.append(metric_data)
            
            await db.commit()
        
        logger.info(f"Stored {len(stored_metrics)} financial metrics for {stock_symbol}")
        
        # Send to frontend via WebSocket
        await ws_manager.broadcast_message({
            "type": "financial_metrics",
            "data": {
                "stock_symbol": stock_symbol,
                "metrics": stored_metrics,
                "total_quarters": len(stored_metrics)
            }
        })
        
        return stored_metrics
        
    except Exception as e:
        logger.error(f"Error processing financial metrics for {stock_symbol}: {e}")
        return []

        

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



# async def convert_xml_to_pdf(xml_url):
#     try:
#         logger.info(f"Fetching XML from URL: {xml_url}")
#         headers = {"User-Agent": "Mozilla/5.0"}
#         res = requests.get(xml_url, headers=headers, timeout=10)
#         res.raise_for_status()
        
#         if not res.content:
#             logger.error("Empty response received from XML URL")
#             return None
            
#         root = ET.fromstring(res.content)
#         if root is None:
#             logger.error("Failed to parse XML content")
#             return None

#         data = {}
#         found_fields = 0

#         for field in fields:
#             for ns in ['in', 'in2']:
#                 try:
#                     el = root.find(f".//{ns}:{field}", namespaces)
#                     if el is not None and el.text:
#                         data[field] = el.text.strip()
#                         found_fields += 1
#                         break  # found in one namespace, skip the rest
#                 except ET.ParseError as e:
#                     logger.error(f"XML parsing error for field {field}: {str(e)}")
#                     continue

#         if found_fields == 0:
#             logger.warning("No fields found in XML document")
#             return None

#         # Create PDF from the extracted data
#         if data:
#             try:
#                 # Ensure PDF directory exists
#                 pdf_dir = "files/pdf"
#                 os.makedirs(pdf_dir, exist_ok=True)
                
#                 # Create stable PDF filename based on XML URL hash to prevent duplicates
#                 import hashlib
#                 xml_hash = hashlib.md5(xml_url.encode()).hexdigest()[:8]
#                 company_name = data.get('NSESymbol', 'Unknown').replace('/', '_')
#                 pdf_filename = f"CA_{company_name}_{xml_hash}.pdf"
#                 pdf_path = os.path.join(pdf_dir, pdf_filename)
                
#                 # Check if PDF already exists - if so, return existing URL
#                 if os.path.exists(pdf_path):
#                     logger.info(f"📄 PDF already exists for {company_name}: {pdf_filename}")
#                     web_url = f"http://localhost:5000/files/pdf/{pdf_filename}"
#                     return web_url
                
#                 # Create PDF document with better margins
#                 doc = SimpleDocTemplate(
#                     pdf_path, 
#                     pagesize=letter,
#                     rightMargin=50, leftMargin=50,
#                     topMargin=50, bottomMargin=50
#                 )
                
#                 styles = getSampleStyleSheet()
#                 story = []
                
#                 # Enhanced title with company info
#                 company_info = f"{data.get('NSESymbol', 'N/A')} - {data.get('NameOfTheCompany', 'Corporate Announcement')}"
#                 title_style = ParagraphStyle(
#                     'CustomTitle',
#                     parent=styles['Title'],
#                     fontSize=18,
#                     spaceAfter=20,
#                     alignment=1,  # Center
#                     textColor=colors.darkblue,
#                     fontName='Helvetica-Bold'
#                 )
#                 story.append(Paragraph(company_info, title_style))
                
#                 # Subtitle
#                 subtitle_style = ParagraphStyle(
#                     'Subtitle',
#                     parent=styles['Heading2'],
#                     fontSize=12,
#                     spaceAfter=30,
#                     alignment=1,
#                     textColor=colors.grey,
#                     fontName='Helvetica'
#                 )
#                 story.append(Paragraph("Corporate Announcement Details", subtitle_style))
                
#                 # Create a more organized layout
#                 heading_style = ParagraphStyle(
#                     'FieldHeading',
#                     parent=styles['Heading3'],
#                     fontSize=11,
#                     spaceBefore=15,
#                     spaceAfter=5,
#                     textColor=colors.darkblue,
#                     fontName='Helvetica-Bold'
#                 )
                
#                 content_style = ParagraphStyle(
#                     'FieldContent',
#                     parent=styles['Normal'],
#                     fontSize=10,
#                     spaceAfter=10,
#                     fontName='Helvetica',
#                     leftIndent=20
#                 )
                
#                 # Priority fields first
#                 priority_fields = [
#                     'NSESymbol', 'NameOfTheCompany', 'ReasonOfChange', 
#                     'Designation', 'NameOfThePersonOrAuditorOrAuditFirmOrRTA',
#                     'EffectiveDateOfAppointmentOrResignationOrRemovalOrDisqualificationOrCessationOrVacationOfOfficeDueToStatutoryAuthorityOrderOrAdditionalChargeOrChangeInDesignation'
#                 ]
                
#                 # Add priority fields
#                 for field in priority_fields:
#                     if field in data and data[field]:
#                         formatted_field = format_field_name(field)
#                         story.append(Paragraph(formatted_field, heading_style))
#                         story.append(Paragraph(data[field], content_style))
                
#                 # Add remaining fields
#                 remaining_fields = [k for k in data.keys() if k not in priority_fields and data[k]]
#                 if remaining_fields:
#                     story.append(Paragraph("Additional Information", heading_style))
#                     for field in remaining_fields:
#                         formatted_field = format_field_name(field)
#                         story.append(Paragraph(f"<b>{formatted_field}:</b> {data[field]}", content_style))
                
#                 # Build PDF
#                 doc.build(story)
#                 logger.info(f"Successfully created PDF: {pdf_path}")
                
#                 # Return the web-accessible URL instead of file path
#                 web_url =f"http://localhost:5000/files/pdf/{pdf_filename}"
#                 # web_url = f"http://122.165.113.41:5000/files/pdf/{pdf_filename}"
#                 return web_url
                
#             except Exception as e:
#                 logger.error(f"Error creating PDF: {str(e)}")
#                 return None
#         else:
#             logger.warning("No data extracted from XML, PDF not created")
#             return None
#     except Exception as e:
#         logger.error(f"Error in convert_xml_to_pdf: {str(e)}")
#         return None

async def convert_xml_to_pdf(xml_url):
    try:
        logger.info(f"Starting XML to PDF conversion for URL: {xml_url}")
        headers = {"User-Agent": "Mozilla/5.0"}
        
        # Log directory creation
        pdf_dir = "files/pdf"
        logger.info(f"Ensuring PDF directory exists: {pdf_dir}")
        os.makedirs(pdf_dir, exist_ok=True)
        if not os.path.exists(pdf_dir):
            logger.error(f"Failed to create PDF directory: {pdf_dir}")
            return None
        else:
            logger.info(f"PDF directory confirmed: {pdf_dir}")

        # Fetch XML using async HTTP client
        logger.info("Fetching XML content...")
        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                res = await client.get(xml_url, headers=headers, timeout=10)
                res.raise_for_status()
                logger.info(f"XML fetch status code: {res.status_code}")
                
                if not res.content:
                    logger.error("Empty response received from XML URL")
                    return None
            except httpx.RequestError as e:
                logger.error(f"Network error fetching XML: {e}")
                return None
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching XML: {e.response.status_code}")
                return None
            
        # Parse XML
        logger.info("Parsing XML content...")
        root = ET.fromstring(res.content)
        if root is None:
            logger.error("Failed to parse XML content")
            return None

        # Get namespaces and extract data
        namespaces = dict([node for node in root.attrib.items() if node[0].startswith('xmlns:')])
        if '}' in root.tag:
            ns = root.tag.split('}')[0].strip('{')
            namespaces['xmlns'] = ns
        logger.info(f"Found namespaces: {namespaces}")

        data = {}
        found_fields = 0

        # Extract all elements
        logger.info("Extracting elements from XML...")
        for elem in root.iter():
            if '}' in elem.tag:
                tag = elem.tag.split('}')[1]
            else:
                tag = elem.tag
                
            if elem.text and elem.text.strip():
                value = elem.text.strip()
                logger.info(f"Found field: {tag}")
                data[tag] = value
                found_fields += 1

        if found_fields == 0:
            logger.warning("No fields found in XML document")
            return None

        # Create PDF
        if data:
            try:
                # Create filename
                company_name = data.get('NSESymbol', data.get('NameOfTheCompany', 'Unknown')).replace('/', '_')
                pdf_filename = f"CA_{company_name}_{int(time.time())}.pdf"
                pdf_path = os.path.join(pdf_dir, pdf_filename)  # Use absolute path
                logger.info(f"Attempting to create PDF at absolute path: {pdf_path}")
                
                # Verify directory is writable
                if not os.access(pdf_dir, os.W_OK):
                    logger.error(f"PDF directory is not writable: {pdf_dir}")
                    return None

                # Create PDF
                doc = SimpleDocTemplate(
                    pdf_path, 
                    pagesize=letter,
                    rightMargin=50, leftMargin=50,
                    topMargin=50, bottomMargin=50
                )
                
                styles = getSampleStyleSheet()
                story = []
                
                # Add content
                title = f"{data.get('NSESymbol', 'N/A')} - {data.get('NameOfTheCompany', 'Corporate Announcement')}"
                title_style = ParagraphStyle(
                    'CustomTitle',
                    parent=styles['Title'],
                    fontSize=18,
                    spaceAfter=20,
                    alignment=1,
                    textColor=colors.darkblue,
                    fontName='Helvetica-Bold'
                )
                story.append(Paragraph(title, title_style))
                
                # Add all fields
                for field, value in data.items():
                    if value and field not in ['NSESymbol', 'NameOfTheCompany']:
                        field_name = ' '.join(field.split('_')).title()
                        story.append(Paragraph(f"<b>{field_name}:</b>", styles['Heading3']))
                        story.append(Paragraph(value, styles['Normal']))
                        story.append(Spacer(1, 10))
                
                # Build PDF
                logger.info("Building PDF document...")
                doc.build(story)
                
                # Verify PDF was created and is readable
                if os.path.exists(pdf_path):
                    if os.access(pdf_path, os.R_OK):
                        pdf_size = os.path.getsize(pdf_path)
                        logger.info(f"PDF created successfully at {pdf_path} (size: {pdf_size} bytes)")
                        web_url = f"{BASE_URL}/files/pdf/{pdf_filename}"
                        logger.info(f"PDF accessible at URL: {web_url}")
                        
                        # List directory contents for verification
                        logger.info(f"Directory contents of {pdf_dir}:")
                        for f in os.listdir(pdf_dir):
                            logger.info(f"- {f}")
                        
                        return web_url
                    else:
                        logger.error(f"PDF file exists but is not readable: {pdf_path}")
                        return None
                else:
                    logger.error(f"PDF file not found after creation attempt: {pdf_path}")
                    return None
            except Exception as e:
                logger.error(f"Error creating PDF: {str(e)}")
                logger.error(f"Current working directory: {os.getcwd()}")
                return None
        else:
            logger.warning("No data extracted from XML")
            return None
            
    except Exception as e:
        logger.error(f"Error in convert_xml_to_pdf: {str(e)}")
        return None
  
def format_field_name(field_name):
    """Convert camelCase field names to readable format"""
    # Add space before uppercase letters
    formatted = ''.join([' ' + c if c.isupper() else c for c in field_name]).strip()
    # Replace common abbreviations
    replacements = {
        'NSE': 'NSE',
        'BSE': 'BSE', 
        'KMP': 'KMP',
        'RTA': 'RTA',
        'RPT': 'RPT'
    }
    for old, new in replacements.items():
        formatted = formatted.replace(old, new)
    return formatted.title()




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
  
        ###### x --------- sending watchlist message -------x ########
        #### this is getting the group id and keywords from the google sheet
        try:
            group_id_keywords = await load_group_keywords_async()
        except Exception as e:
            logger.error(f"Error loading group keywords: {str(e)}")
            logger.info("Continuing without custom group keywords due to loading error")
            group_id_keywords = {}  # Set empty dict to continue processing without custom groups

        ###### X --------------------------------------------X #########      
        
        #if new rows  
        if len(new_rows) > 0:
                
            #################################################################
            # Now process all rows and send messages
                
            for index, row in new_rows.iterrows():
                attachment_file = str(row['attchmntFile'])
                
                print(f"Processing row {index}: {row['symbol']} - {row['sm_name']}")
                
                # If it's an XML file, convert it and use the PDF URL
                if attachment_file.lower().endswith('.xml'):
                    pdf_url = await convert_xml_to_pdf(attachment_file)
                    if pdf_url:
                        attachment_file = pdf_url
                        logger.info(f"Using converted PDF URL: {pdf_url}")
                
                print(f"Final attachment file: {attachment_file}")
                
                # Create message with the final attachment URL (PDF if converted, otherwise original)
                # Always show the full URL in the link text
                message = f'''<b>{row['symbol']} - {row['sm_name']}</b>\n\n{row['desc']}\n\nFile:\n <a href="{attachment_file}">{attachment_file}</a>'''

                print(f"Message created for {row['symbol']}")
                
                # Send the message This will send all the messages to the trade_mvd chat id WHich is used to testing or to check if the script is running or not
                await trigger_test_message("@trade_mvd", message, "test", row['symbol'], row['sm_name'], row['desc'], attachment_file)
                
                
                ##### X------------ THIS IS WATCHING LIST SENDING -------X ########
                # # check if the company is in the SME list
                # if row["sm_name"] in SME_companies:
                #     await trigger_watchlist_message(message)
                #     await update_watchlist_file(new_rows)
                # # check if the company is in the BSE_NSE_companies list
                # if row["sm_name"] in BSE_NSE_companies:
                #     await trigger_watchlist_message(message)
                #     await update_watchlist_file(new_rows)
                ##### X -------------------------------------------------X ########   
                    
                # Convert all row values to lowercase strings and check for keyword matches
                row_values = [str(val).lower() for val in row]  
                
                ###############################################################
                ###### x --------- sending watchlist message -------x ########
                #### this is getting the group id and keywords from the google sheet
                ## now we need to check if the new_rows is in the group_id_keywords
                for group_id, data in group_id_keywords.items():
                    # Extract keywords and option from the data structure
                    keywords = data.get('keywords', [])
                    option = data.get('option', '')
                    
                    # Convert keywords to lowercase list
                    keywords_lower = [str(kw).lower() for kw in keywords]

                    if any(any(kw in val for val in row_values) for kw in keywords_lower):
                        # message = f"""<b>{row['symbol']} - {row['sm_name']}</b>\n\n{row['desc']}\n\n<i>{row['attchmntText']}</i>\n\n<b>File:</b>\n{row['attchmntFile']}"""
                        await trigger_test_message(group_id, message, option, row['symbol'], row['sm_name'], row['desc'], attachment_file)
                ###### X --------------------------------------------X #########      
                ################################################################
                
                
                
                ################################################################
                ###### x --------- sending result concal message -------x ########
                #### this is getting the group id and keywords from the google sheet
                for group_id, keywords in result_concall_keywords.items():
                    # Convert keywords to lowercase list
                    result_concall_keywords_lower = [str(kw).lower() for kw in keywords]
                    if any(any(kw in val for val in row_values) for kw in result_concall_keywords_lower):
                        # ocr the pdf
                        financial_metrics = await main_ocr_async(attachment_file)
                        print("FINANCIAL METRICS ARE - ", financial_metrics)
                        
                        # Send message to Telegram and get message ID
                        message_id = await trigger_test_message(group_id, message, "result_concall", row['symbol'], row['sm_name'], row['desc'], attachment_file)
                        
                        # Process and store financial metrics
                        if financial_metrics:
                            await process_financial_metrics(
                                financial_metrics, 
                                row['symbol'], 
                                message_id
                            )
                ###### X --------------------------------------------X #########      
                ################################################################
            
            # For CSV storage, keep original URLs to maintain duplicate detection
            new_rows_for_csv = new_rows.copy()
            
            # Restore original XML URLs in the CSV copy to maintain duplicate detection
            for index, row in new_rows.iterrows():
                if row['attchmntFile'].startswith(f"{BASE_URL}/files/pdf/"):
                    # Find the original XML URL from the API data
                    api_row = api_df[api_df['symbol'] == row['symbol']]
                    if not api_row.empty:
                        original_url = api_row.iloc[0]['attchmntFile']
                        new_rows_for_csv.iloc[index, new_rows_for_csv.columns.get_loc('attchmntFile')] = original_url
                        logger.info(f"📝 Restored original URL for CSV: {row['symbol']} -> {original_url}")
            
            # Update main CSV file with ORIGINAL URLs (for duplicate detection)
            logger.info("Updating CSV file with original URLs (for duplicate detection)")
            df1_updated = pd.concat([new_rows_for_csv, df1], ignore_index=True).drop_duplicates()
            async with aiofiles.open(csv_file_path, mode='w') as f:
                await f.write(df1_updated.to_csv(index=False))
            logger.info(f"Updated CSV file saved with {len(df1_updated)} total rows")

            
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
        logger.error(f"Unexpected error in CA_sme: {str(e)}")
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
            # Increased wait time to reduce interference with AI analyzer
            await asyncio.sleep(60)  # Wait for 60 seconds before running it again
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
    global ai_processing_active
    logger.info("starting thescript equities ")
    while True:
        try:
            # Pause background task if AI processing is active
            if ai_processing_active:
                logger.info("AI processing active, pausing background task...")
                await asyncio.sleep(10)  # Check again in 10 seconds
                continue
                
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
            # Increased wait time to reduce interference with AI analyzer
            await asyncio.sleep(60)  # Wait for 60 seconds before running it again
        except Exception as e:
            logger.error(f"Error in run_periodic_task_equities: {str(e)}")
            logger.info("Error occurred in Equities task, waiting 30 seconds before retrying...")
            await asyncio.sleep(30)  # Wait for 30 seconds before retrying




async def verify_session(request: Request) -> Optional[Dict]:
    """Verify session token and return user data"""
    auth_header = request.headers.get('Authorization')
    
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    
    session_token = auth_header.replace('Bearer ', '')
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT s.user_id, s.expires_at, u.username
                FROM sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_token = ?
            """, (session_token,))
            
            result = await cursor.fetchone()
            
            if not result:
                return None
            
            user_id, expires_at, username = result
            
            # Check if session has expired
            expires_time = datetime.fromisoformat(expires_at)
            if get_ist_now() > expires_time:
                # Delete expired session
                await db.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
                await db.commit()
                return None
            
            return {
                "user_id": user_id,
                "username": username,
                "session_token": session_token
            }
    except Exception as e:
        logger.error(f"Error verifying session: {e}")
        return None

@app.get("/")
async def root():
    """Redirect to login page"""
    return FileResponse('static/login.html')

@app.get("/dashboard")
async def get_dashboard():
    """Serve the main dashboard (authentication checked client-side)"""
    # Authentication is checked on the client side via JavaScript
    # The dashboard will redirect to login if no valid session token exists
    return FileResponse('static/index.html')

@app.get("/home")
async def home():
    return "New automation method Trillionaire"

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await ws_manager.connect(websocket)
    try:
        # Send existing messages to new connection (get all messages, no limit)
        messages = await get_messages_from_db(limit=0)
        await websocket.send_json({
            "type": "messages_list",
            "messages": messages
        })
        
        # Keep connection alive
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

@app.post("/api/trigger_message")
async def receive_trigger_message(message_data: MessageData):
    """Receive trigger_test_message calls and broadcast to UI"""
    try:
        # Add timestamp if not provided
        if not message_data.timestamp:
            message_data.timestamp = get_ist_now().isoformat()
        
        # Parse message content if not already structured
        if not message_data.symbol and not message_data.company_name:
            parsed = parse_message_content(message_data.message)
            message_data.symbol = parsed.get("symbol", "")
            message_data.company_name = parsed.get("company_name", "")
            message_data.description = parsed.get("description", "")
            message_data.file_url = parsed.get("file_url", "")
        
        # Skip "test" option completely - no DB, no WebSocket, Telegram only
        if message_data.option == "test":
            logger.info(f"Test message - Telegram only (not saved to DB or dashboard): {message_data.symbol} - {message_data.company_name}")
            return {"success": True, "message": "Test message sent to Telegram only"}
        
        # Save to database (all options except "test")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO messages 
                (chat_id, message, timestamp, symbol, company_name, description, file_url, raw_message, option)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_data.chat_id,
                message_data.message,
                message_data.timestamp,
                message_data.symbol,
                message_data.company_name,
                message_data.description,
                message_data.file_url,
                message_data.message,
                message_data.option
            ))
            await db.commit()
        
        # Broadcast to WebSocket clients (only for non-test messages)
        await ws_manager.broadcast_message({
            "type": "new_message",
            "message": message_data.dict()
        })
        
        logger.info(f"Message saved to DB and broadcasted: {message_data.symbol} - {message_data.company_name}")
        
        return {"success": True, "message": "Message received and broadcasted"}
        
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def get_messages_from_db(limit: int = 100) -> List[Dict]:
    """Get messages from database"""
    async with aiosqlite.connect(DB_PATH) as db:
        if limit > 0:
            cursor = await db.execute("""
                SELECT * FROM messages 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
        else:
            cursor = await db.execute("""
                SELECT * FROM messages 
                ORDER BY timestamp DESC
            """)
        
        rows = await cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        
        return [dict(zip(columns, row)) for row in rows]

@app.get("/api/verify_session")
async def verify_session_endpoint(request: Request):
    """Verify if session is valid"""
    user = await verify_session(request)
    if user:
        return {
            "valid": True,
            "username": user["username"]
        }
    return {
        "valid": False,
        "message": "Session expired or invalid"
    }

@app.get("/api/messages")
async def get_messages(limit: int = 0):
    """Get all messages"""
    try:
        messages = await get_messages_from_db(limit)
        return {"success": True, "messages": messages}
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/financial_metrics")
async def get_financial_metrics(limit: int = 100):
    """Get financial metrics data"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            if limit > 0:
                cursor = await db.execute("""
                    SELECT * FROM financial_metrics 
                    ORDER BY reported_at DESC 
                    LIMIT ?
                """, (limit,))
            else:
                cursor = await db.execute("""
                    SELECT * FROM financial_metrics 
                    ORDER BY reported_at DESC
                """)
            
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            
            metrics = [dict(zip(columns, row)) for row in rows]
            
            return {"success": True, "metrics": metrics}
    except Exception as e:
        logger.error(f"Error fetching financial metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_local_pdf_async_optimized(pdf_path: str):
    """Memory-optimized PDF processing with background task pausing, batch processing, and memory monitoring."""
    global ai_processing_active

    
    try:
        # Set AI processing flag to pause background tasks
        ai_processing_active = True
        
        # Monitor initial memory
        memory_start = psutil.virtual_memory().percent
        logger.info(f"🚀 Starting MEMORY-OPTIMIZED PDF processing: {pdf_path}")
        logger.info(f"💾 Initial memory usage: {memory_start:.1f}%")
        logger.info("⏸️ Background tasks paused for faster processing")
        
        start_time = time.time()
        
        # Step 1: Convert PDF to images with memory optimization (150 DPI + smart compression)
        logger.info("📄 Converting PDF to images with memory optimization (DPI: 150, compression: 9)...")
        image_paths, images_folder = await pdf_to_png_async(pdf_path, base_images_folder="images")
        
        if not image_paths:
            logger.error("No images were created from the PDF")
            return None
        
        convert_time = time.time() - start_time
        memory_after_convert = psutil.virtual_memory().percent
        logger.info(f"✅ Created {len(image_paths)} images in {convert_time:.2f}s")
        logger.info(f"💾 Memory after conversion: {memory_after_convert:.1f}%")
        
        # Memory check and cleanup if needed
        if memory_after_convert > 75:
            logger.info("⚠️ High memory usage, forcing cleanup...")
            gc.collect()
            memory_after_gc = psutil.virtual_memory().percent
            logger.info(f"💾 Memory after cleanup: {memory_after_gc:.1f}%")
        
        # Step 2: Process pages with batch processing for memory control
        logger.info(f"📄 Processing {len(image_paths)} pages with batch processing (5 pages per batch)")
        
        # Step 3: Run OCR with memory-optimized batch processing
        ocr_start = time.time()
        logger.info("🔍 Running memory-optimized OCR processing...")
        ocr_results = await process_ocr_from_images_async(image_paths)
        
        if not ocr_results:
            logger.error("OCR processing failed")
            return None
            
        ocr_time = time.time() - ocr_start
        memory_after_ocr = psutil.virtual_memory().percent
        logger.info(f"✅ OCR completed in {ocr_time:.2f}s. Found {len(ocr_results.get('financial_pages', []))} pages with financial content")
        logger.info(f"💾 Memory after OCR: {memory_after_ocr:.1f}%")
        
        # Step 4: Encode financial images with memory-optimized batch processing
        encoded_images = []
        if ocr_results.get('detected_image_paths'):
            logger.info("🖼️ Encoding financial images with memory optimization...")
            encode_start = time.time()
            encoded_images = await encode_images_async(ocr_results['detected_image_paths'])
            encode_time = time.time() - encode_start
            memory_after_encode = psutil.virtual_memory().percent
            logger.info(f"✅ Encoded {len(encoded_images)} images in {encode_time:.2f}s")
            logger.info(f"💾 Memory after encoding: {memory_after_encode:.1f}%")
        
        # Memory cleanup before AI analysis
        if memory_after_ocr > 70:
            logger.info("⚠️ Performing memory cleanup before AI analysis...")
            gc.collect()
            memory_before_ai = psutil.virtual_memory().percent
            logger.info(f"💾 Memory before AI analysis: {memory_before_ai:.1f}%")
        
        # Step 5: Use financial_text if available, otherwise use all_pages_text
        text_for_analysis = ocr_results.get('financial_text') or ocr_results.get('all_pages_text', '')
        
        if not text_for_analysis:
            logger.warning("No text extracted from PDF")
            return None
        
        # Step 6: AI analysis with text AND images for maximum accuracy
        ai_start = time.time()
        logger.info("🤖 Starting comprehensive AI analysis (text + images)...")
        financial_metrics = await analyze_financial_metrics_async(text_for_analysis, encoded_images)
        
        ai_time = time.time() - ai_start
        total_time = time.time() - start_time
        memory_final = psutil.virtual_memory().percent
        
        logger.info(f"✅ AI analysis completed in {ai_time:.2f}s")
        logger.info(f"🎉 TOTAL PROCESSING TIME: {total_time:.2f}s")
        logger.info(f"💾 Final memory usage: {memory_final:.1f}% (started at {memory_start:.1f}%)")
        logger.info(f"📊 Memory efficiency: {memory_final - memory_start:+.1f}% change")
        
        # Post-OCR cleanup: Delete images immediately after successful processing
        if images_folder and CLEANUP_CONFIG["post_ocr_cleanup"]:
            await post_ocr_cleanup_async(images_folder)
        
        return financial_metrics
        
    except Exception as e:
        logger.error(f"Error in optimized PDF processing: {str(e)}")
        # Cleanup images even on error
        if 'images_folder' in locals() and images_folder and CLEANUP_CONFIG["post_ocr_cleanup"]:
            await post_ocr_cleanup_async(images_folder)
        return None
    finally:
        # Always resume background tasks
        ai_processing_active = False
        logger.info("▶️ Background tasks resumed")

# Keep the original function as backup
async def process_local_pdf_async(pdf_path: str):
    """Process a local PDF file using OCR and extract financial metrics."""
    try:
        logger.info(f"Starting local PDF processing: {pdf_path}")
        
        # Convert PDF to images
        logger.info("Converting PDF to images...")
        image_paths, images_folder = await pdf_to_png_async(pdf_path, base_images_folder="images")
        
        if not image_paths:
            logger.error("No images were created from the PDF")
            return None
        
        logger.info(f"Created {len(image_paths)} images from PDF")
        
        # Run OCR on all pages
        logger.info("Running OCR on all pages...")
        ocr_results = await process_ocr_from_images_async(image_paths)
        
        if not ocr_results:
            logger.error("OCR processing failed")
            return None
            
        logger.info(f"OCR completed. Found {len(ocr_results.get('financial_pages', []))} pages with financial content")
        
        # Encode financial images to base64
        encoded_images = []
        if ocr_results.get('detected_image_paths'):
            logger.info("Encoding financial images...")
            encoded_images = await encode_images_async(ocr_results['detected_image_paths'])
            logger.info(f"Encoded {len(encoded_images)} images")
        
        # Use financial_text if available, otherwise use all_pages_text
        text_for_analysis = ocr_results.get('financial_text') or ocr_results.get('all_pages_text', '')
        
        if not text_for_analysis:
            logger.warning("No text extracted from PDF")
            return None
        
        # Analyze with AI
        logger.info("Starting AI analysis...")
        financial_metrics = await analyze_financial_metrics_async(text_for_analysis, encoded_images)
        
        logger.info("AI analysis completed successfully")
        return financial_metrics
        
    except Exception as e:
        logger.error(f"Error in process_local_pdf_async: {str(e)}")
        return None

# Clear messages API endpoint removed by user request

@app.post("/api/ai_analyze")
async def ai_analyze(file: UploadFile = File(...)):
    """AI analyzer endpoint that processes PDF files using OCR and returns financial metrics"""
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        
        # Create temporary directory for uploaded files
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        
        # Save uploaded file temporarily
        temp_file_path = os.path.join(temp_dir, file.filename)
        
        async with aiofiles.open(temp_file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        logger.info(f"Processing uploaded PDF: {file.filename}")
        
        # Process the PDF using OPTIMIZED local processing
        financial_metrics = await process_local_pdf_async_optimized(temp_file_path)
        
        # Clean up temporary file
        try:
            await aiofiles.os.remove(temp_file_path)
        except Exception as e:
            logger.warning(f"Could not remove temporary file {temp_file_path}: {e}")
        
        if not financial_metrics:
            error_msg = "No financial metrics extracted from the document. This could be due to: 1) PDF contains no financial data, 2) OCR failed to extract text, or 3) AI couldn't parse the financial information."
            logger.warning(f"No financial metrics extracted from {file.filename}")
            raise HTTPException(status_code=422, detail="No financial metrics could be extracted from the PDF")
        
        logger.info(f"Successfully processed PDF: {file.filename}")
        return {
            "success": True,
            "filename": file.filename,
            "financial_metrics": financial_metrics,
            "message": "PDF processed successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in AI analyzer: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")

# OCR dependencies test endpoint removed - was only for debugging

@app.post("/api/pause_background_tasks")
async def pause_background_tasks():
    """Temporarily pause background tasks for faster AI processing"""
    global ai_processing_active
    ai_processing_active = True
    return {"success": True, "message": "Background tasks paused"}

@app.post("/api/resume_background_tasks") 
async def resume_background_tasks():
    """Resume background tasks after AI processing"""
    global ai_processing_active
    ai_processing_active = False
    return {"success": True, "message": "Background tasks resumed"}

@app.get("/api/place_order_sheet")
async def get_place_order_sheet():
    """Get place order data from Google Sheets"""
    try:
        sheet_id = "1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM"
        gid = "1933500776"  # Market Open Order sheet
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(sheet_url)
            response.raise_for_status()
            
            df = pd.read_csv(io.StringIO(response.text))
            
            # Replace NaN values with empty strings to avoid JSON serialization errors
            df = df.fillna('')
            
            # Convert to list of dictionaries for JSON response
            sheet_data = df.to_dict('records')
            
            # Filter out completely empty rows
            filtered_data = []
            for row in sheet_data:
                if any(str(value).strip() for value in row.values() if value != ''):
                    # Clean up the row data for JSON serialization
                    cleaned_row = {}
                    for key, value in row.items():
                        if pd.isna(value) or value == 'nan':
                            cleaned_row[key] = ''
                        else:
                            cleaned_row[key] = str(value).strip()
                    filtered_data.append(cleaned_row)
            
            logger.info(f"Loaded {len(filtered_data)} rows from place_order sheet")
            return {
                "success": True,
                "data": filtered_data,
                "total_rows": len(filtered_data)
            }
            
    except Exception as e:
        logger.error(f"Error loading place order sheet: {e}")
        return {
            "success": False,
            "message": f"Error loading sheet data: {str(e)}",
            "data": []
        }

@app.get("/api/session_status")
async def get_session_status():
    """Check if there's a valid active session"""
    try:
        session_file = "kotak_session.json"
        
        if not os.path.exists(session_file):
            return {
                "session_active": False,
                "message": "No session found"
            }
        
        async with aiofiles.open(session_file, 'r') as f:
            content = await f.read()
            session_data = json.loads(content)
        
        expires_at_str = session_data.get('expires_at')
        if not expires_at_str:
            return {
                "session_active": False,
                "message": "Invalid session data"
            }
        
        # Parse expiry time
        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
        current_time = get_ist_now()
        
        if current_time < expires_at:
            return {
                "session_active": True,
                "message": "Session is active",
                "expires_at": expires_at_str,
                "sid": session_data.get('sid', 'N/A')
            }
        else:
            return {
                "session_active": False,
                "message": "Session expired"
            }
            
    except Exception as e:
        logger.error(f"Error checking session status: {e}")
        return {
            "session_active": False,
            "message": "Error checking session"
        }

async def fetch_nse_cm_data_background():
    """
    Background task to fetch NSE CM data and write to Google Sheet
    Runs after successful TOTP authentication
    """
    try:
        logger.info("🔄 Background: Starting NSE CM data fetch...")
        
        # Load session data
        session_file = "kotak_session.json"
        if not os.path.exists(session_file):
            logger.error("Background: Session file not found")
            return
        
        async with aiofiles.open(session_file, 'r') as f:
            content = await f.read()
            session_data = json.loads(content)
        
        access_token = session_data.get('access_token')
        if not access_token:
            logger.error("Background: Access token not found")
            return
        
        # Get file paths
        url = "https://gw-napi.kotaksecurities.com/Files/1.0/masterscrip/v2/file-paths"
        headers = {'accept': '*/*', 'Authorization': f'Bearer {access_token}'}
        
        async with httpx.AsyncClient(verify=False, timeout=30, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                logger.error(f"Background: Failed to fetch file paths")
                return
            
            data = response.json()
            file_paths = data.get('data', {}).get('filesPaths', [])
            
            # Find nse_cm-v1.csv
            nse_cm_url = None
            for path in file_paths:
                if 'nse_cm-v1.csv' in path:
                    nse_cm_url = path
                    break
            
            if not nse_cm_url:
                logger.error("Background: nse_cm-v1.csv not found")
                return
            
            # Download CSV
            logger.info(f"Background: Downloading {nse_cm_url}")
            csv_response = await client.get(nse_cm_url)
            
            if csv_response.status_code != 200:
                logger.error("Background: Failed to download CSV")
                return
            
            # Load DataFrame
            df = pd.read_csv(io.StringIO(csv_response.text))
            logger.info(f"Background: Loaded {len(df)} rows, {len(df.columns)} columns")
            
            # Filter only EQ (Equity) stocks from pGroup column
            if 'pGroup' in df.columns:
                original_count = len(df)
                df = df[df['pGroup'] == 'EQ'].copy()
                filtered_count = len(df)
                logger.info(f"Background: Filtered pGroup='EQ' → {filtered_count} rows (removed {original_count - filtered_count} non-EQ stocks)")
            else:
                logger.warning("Background: pGroup column not found, writing all data")
            
            # Write to Google Sheet
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            import numpy as np
            
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name('google_sheets_credentials.json', scope)
            gsheet_client = gspread.authorize(creds)
            
            spreadsheet = gsheet_client.open_by_key("1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM")
            
            # Find worksheet by gid
            worksheet = None
            for sheet in spreadsheet.worksheets():
                if str(sheet.id) == "1765483913":
                    worksheet = sheet
                    break
            
            if not worksheet:
                logger.error("Background: Worksheet not found")
                return
            
            # Expand sheet if needed
            if worksheet.row_count < len(df) + 1:
                rows_to_add = (len(df) + 1) - worksheet.row_count
                worksheet.add_rows(rows_to_add)
                logger.info(f"Background: Expanded sheet by {rows_to_add} rows")
            
            # Prepare data
            data = [df.columns.tolist()] + df.values.tolist()
            data = [['' if (isinstance(cell, float) and np.isnan(cell)) else cell for cell in row] for row in data]
            
            # Clear and write
            worksheet.clear()
            
            # Write in batches
            batch_size = 5000
            for batch_num in range(0, len(data), batch_size):
                batch_data = data[batch_num:min(batch_num + batch_size, len(data))]
                worksheet.update(f'A{batch_num + 1}', batch_data)
                logger.info(f"Background: Batch written (rows {batch_num + 1}-{batch_num + len(batch_data)})")
            
            logger.info(f"✅ Background: NSE CM data written successfully to Google Sheet")
            
    except Exception as e:
        logger.error(f"❌ Background: NSE CM data fetch failed: {e}")

@app.post("/api/verify_totp")
async def verify_totp(request: TOTPRequest, background_tasks: BackgroundTasks):
    """Verify TOTP code and authenticate with Neo trading system"""
    try:
        # Get credentials from environment variables
        client_credentials = os.getenv("CLIENT_CREDENTIALS")
        mobile_number = os.getenv("MOBILE_NUMBER")
        ucc = os.getenv("UCC")
        mpin = os.getenv("MPIN")
        
        if not all([client_credentials, mobile_number, ucc, mpin]):
            logger.error("Missing required environment variables")
            return {
                "success": False,
                "message": "Server configuration error: Missing credentials"
            }
        
        logger.info(f"Starting Neo authentication with TOTP from UI: {request.totp_code}")
        
        # Format client credentials for Basic auth
        formatted_credentials = f'Basic {client_credentials}'
        
        # Call neo_main_login function with TOTP from UI, rest from .env
        session_data = await neo_main_login(formatted_credentials, mobile_number, ucc, request.totp_code, mpin)
        
        if session_data:
            logger.info("Neo authentication successful")
            
            # Trigger NSE CM data fetch in background after successful auth
            background_tasks.add_task(fetch_nse_cm_data_background)
            logger.info("🚀 Triggered NSE CM data fetch in background")
            
            return {
                "success": True,
                "message": "TOTP verified and session established for the day",
                "session_info": {
                    "sid": session_data.get('data', {}).get('sid', 'N/A'),
                    "expires_at": session_data.get('expires_at', 'N/A')
                },
                "timestamp": get_ist_now().isoformat()
            }
        else:
            logger.warning(f"Neo authentication failed for TOTP: {request.totp_code}")
            return {
                "success": False,
                "message": "Invalid TOTP code or authentication failed"
            }
            
    except Exception as e:
        logger.error(f"Error in Neo TOTP authentication: {e}")
        return {
            "success": False,
            "message": f"Authentication error: {str(e)}"
        }


@app.post("/api/execute_orders")
async def execute_orders(background_tasks: BackgroundTasks):
    """Execute place orders - runs in background, returns job_id immediately"""
    try:
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # Create job entry
        active_jobs[job_id] = JobStatus(
            job_id=job_id,
            type="place_order",
            status="running",
            progress=0,
            message="Starting order execution...",
            started_at=get_ist_now().isoformat()
        )
        
        # Define background task with real-time progress tracking
        async def run_place_orders_background():
            try:
                logger.info(f"[Job {job_id}] Starting PLACE ORDER background task")
                
                # Import order placement modules
                from place_order import get_gsheet_stocks_df as get_order_stocks, get_order_data, place_orders_batch
                from gsheet_stock_get import GSheetStockClient
                
                # Step 1: Load stock data from Google Sheet (10% progress)
                active_jobs[job_id].message = "Loading stock data from Google Sheet..."
                active_jobs[job_id].progress = 10
                
                sheet_url = f"{os.getenv('BASE_SHEET_URL')}{os.getenv('sheet_gid')}"
                gsheet_client = GSheetStockClient()
                df = await gsheet_client.get_stock_dataframe(sheet_url)
                
                all_rows = []
                if df is not None:
                    for index, row in df.iterrows():
                        row_dict = row.to_dict()
                        all_rows.append(row_dict)
                
                total_stocks = len(all_rows)
                logger.info(f"[Job {job_id}] Loaded {total_stocks} stocks from sheet")
                
                # Step 2: Create order data (20% progress)
                active_jobs[job_id].message = f"Creating orders for {total_stocks} stocks..."
                active_jobs[job_id].progress = 20
                
                all_orders = await get_order_data(all_rows)
                total_orders = len(all_orders)
                
                logger.info(f"[Job {job_id}] Created {total_orders} orders ({total_orders//2} stocks × 2 orders)")
                
                # Step 3: Place orders with rate limiting and progress tracking (20% → 90%)
                active_jobs[job_id].message = f"Placing {total_orders} orders..."
                active_jobs[job_id].progress = 25
                
                # Calculate batches (180 per batch with 53s delay = ~196 req/min, 2% under limit)
                batch_size = 180
                total_batches = (total_orders + batch_size - 1) // batch_size
                
                logger.info(f"[Job {job_id}] Will process {total_batches} batches")
                
                progress_start = 25
                progress_end = 85
                progress_range = progress_end - progress_start
                
                all_results = []
                
                for batch_num in range(total_batches):
                    start_idx = batch_num * batch_size
                    end_idx = min(start_idx + batch_size, total_orders)
                    batch_orders = all_orders[start_idx:end_idx]
                    
                    # Update progress for this batch
                    batch_progress = progress_start + int((batch_num / total_batches) * progress_range)
                    active_jobs[job_id].progress = batch_progress
                    active_jobs[job_id].message = f"Placing orders batch {batch_num + 1}/{total_batches} ({end_idx}/{total_orders} orders)"
                    
                    logger.info(f"[Job {job_id}] Processing batch {batch_num + 1}/{total_batches}")
                    
                    # Place orders for this batch
                    batch_results = await place_orders_batch(batch_orders, max_concurrent=5)
                    all_results.extend(batch_results)
                    
                    # Wait if not last batch (rate limiting: 180 orders per 53s = ~196 req/min, 2% buffer)
                    if batch_num < total_batches - 1:
                        await asyncio.sleep(53)  # 53 seconds for optimal speed with safety margin
                
                # Step 4: Count successes (90% progress)
                active_jobs[job_id].message = "Processing results..."
                active_jobs[job_id].progress = 90
                
                successful = sum(1 for r in all_results if r and r.get('status') != 'error')
                failed = total_orders - successful
                
                logger.info(f"[Job {job_id}] Order summary: {successful}/{total_orders} successful")
                
                # Complete (100% progress)
                active_jobs[job_id].status = "completed"
                active_jobs[job_id].progress = 100
                active_jobs[job_id].message = f"Orders executed: {successful} successful, {failed} failed"
                active_jobs[job_id].completed_at = get_ist_now().isoformat()
                active_jobs[job_id].result = {
                    "status": "completed",
                    "total_orders": total_orders,
                    "successful": successful,
                    "failed": failed
                }
                
                logger.info(f"[Job {job_id}] PLACE ORDER completed successfully")
                
                # Broadcast completion to all WebSocket clients
                await ws_manager.broadcast_message({
                    "type": "job_completed",
                    "job": asdict(active_jobs[job_id])
                })
                
            except Exception as e:
                logger.error(f"[Job {job_id}] PLACE ORDER failed: {e}")
                active_jobs[job_id].status = "failed"
                active_jobs[job_id].progress = 0
                active_jobs[job_id].message = f"Order execution failed: {str(e)}"
                active_jobs[job_id].error = str(e)
                active_jobs[job_id].completed_at = get_ist_now().isoformat()
                
                # Broadcast failure to WebSocket clients
                await ws_manager.broadcast_message({
                    "type": "job_failed",
                    "job": asdict(active_jobs[job_id])
                })
        
        # Add task to background
        background_tasks.add_task(run_place_orders_background)
        
        logger.info(f"[Job {job_id}] PLACE ORDER started in background")
        
        return {
            "success": True,
            "job_id": job_id,
            "message": "Order execution started in background",
            "estimated_time": "1-2 minutes"
        }
        
    except Exception as e:
        logger.error(f"Error starting PLACE ORDER background task: {e}")
        return {
            "success": False,
            "message": f"Failed to start order execution: {str(e)}"
        }

@app.post("/api/login")
async def login(request: LoginRequest):
    """Login endpoint - authenticate user and create session"""
    try:
        # Hash the password
        password_hash = hashlib.sha256(request.password.encode()).hexdigest()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Verify credentials
            cursor = await db.execute("""
                SELECT id, username FROM users 
                WHERE username = ? AND password_hash = ?
            """, (request.username, password_hash))
            
            user = await cursor.fetchone()
            
            if not user:
                logger.warning(f"Failed login attempt for username: {request.username}")
                return {
                    "success": False,
                    "message": "Invalid username or password"
                }
            
            user_id, username = user
            
            # Generate session token
            session_token = secrets.token_urlsafe(32)
            created_at = get_ist_now()
            expires_at = created_at + timedelta(hours=8)  # Session expires in 8 hours
            
            # Create session
            await db.execute("""
                INSERT INTO sessions (session_token, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
            """, (session_token, user_id, created_at.isoformat(), expires_at.isoformat()))
            
            # Update last login
            await db.execute("""
                UPDATE users SET last_login = ? WHERE id = ?
            """, (created_at.isoformat(), user_id))
            
            await db.commit()
            
            logger.info(f"Successful login for user: {username}")
            
            return {
                "success": True,
                "message": "Login successful",
                "session_token": session_token,
                "username": username,
                "expires_at": expires_at.isoformat()
            }
            
    except Exception as e:
        logger.error(f"Login error: {e}")
        return {
            "success": False,
            "message": "An error occurred during login"
        }

@app.post("/api/logout")
async def logout(request: Request):
    """Logout endpoint - invalidate session"""
    try:
        user = await verify_session(request)
        
        if not user:
            return {"success": False, "message": "No active session"}
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                DELETE FROM sessions WHERE session_token = ?
            """, (user['session_token'],))
            await db.commit()
        
        logger.info(f"User {user['username']} logged out")
        
        return {
            "success": True,
            "message": "Logged out successfully"
        }
        
    except Exception as e:
        logger.error(f"Logout error: {e}")
        return {
            "success": False,
            "message": "Error during logout"
        }
        

## Create an endpoint to get the quotes updated. call the get_quote.py main function        
@app.get("/api/get_quotes_updated")
async def get_quotes_updated(background_tasks: BackgroundTasks):
    """Get quotes updated - runs in background, returns job_id immediately"""
    try:
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # Create job entry
        active_jobs[job_id] = JobStatus(
            job_id=job_id,
            type="get_quotes",
            status="running",
            progress=0,
            message="Starting quote fetch process...",
            started_at=get_ist_now().isoformat()
        )
        
        # Define background task with real-time progress tracking
        async def run_get_quotes_background():
            try:
                logger.info(f"[Job {job_id}] Starting GET QUOTES background task")
                
                # Import quote fetching modules
                from get_quote import (
                    get_gsheet_stocks_df, get_symbol_from_gsheet_stocks_df,
                    flatten_quote_result_list, fetch_ohlc_from_quote_result,
                    update_df_with_quote_ohlc, write_quote_ohlc_to_gsheet,
                    KotakQuoteClient
                )
                from gsheet_stock_get import GSheetStockClient
                
                # Step 1: Get sheet data (5% progress)
                active_jobs[job_id].message = "Loading stock data from Google Sheet..."
                active_jobs[job_id].progress = 5
                
                sheet_url = f"{os.getenv('BASE_SHEET_URL')}{os.getenv('sheet_gid')}"
                gsheet_client = GSheetStockClient()
                df = await gsheet_client.get_stock_dataframe(sheet_url)
                all_rows = await get_gsheet_stocks_df(df)
                
                logger.info(f"[Job {job_id}] Loaded {len(all_rows)} stocks from sheet")
                
                # Step 2: Create symbols list (10% progress)
                active_jobs[job_id].message = "Creating symbol list..."
                active_jobs[job_id].progress = 10
                
                symbols_list, valid_indices = await get_symbol_from_gsheet_stocks_df(all_rows)
                total_symbols = len(symbols_list)
                
                logger.info(f"📊 Created symbols: {total_symbols}")
                logger.info(f"📊 Valid indices: {len(valid_indices)}")
                logger.info(f"[Job {job_id}] Created {total_symbols} valid symbols")
                
                # Step 3: Fetch quotes with rate limiting and progress tracking (10% → 80%)
                active_jobs[job_id].message = f"Fetching quotes for {total_symbols} stocks..."
                active_jobs[job_id].progress = 15
                
                # Calculate batches (180 per batch with 53s delay = ~196 req/min, 2% under limit)
                batch_size = 180
                total_batches = (total_symbols + batch_size - 1) // batch_size
                
                logger.info(f"[Job {job_id}] Will process {total_batches} batches")
                
                # Manually call KotakQuoteClient with progress tracking
                quote_client = KotakQuoteClient()
                all_quote_results = []
                
                progress_start = 15
                progress_end = 75
                progress_range = progress_end - progress_start
                
                batch_lengths = []  # Track response lengths per batch
                
                for batch_num in range(total_batches):
                    start_idx = batch_num * batch_size
                    end_idx = min(start_idx + batch_size, total_symbols)
                    batch_symbols = symbols_list[start_idx:end_idx]
                    
                    # Update progress for this batch
                    batch_progress = progress_start + int((batch_num / total_batches) * progress_range)
                    active_jobs[job_id].progress = batch_progress
                    active_jobs[job_id].message = f"Fetching batch {batch_num + 1}/{total_batches} ({end_idx}/{total_symbols} stocks)"
                    
                    logger.info(f"[Job {job_id}] Processing batch {batch_num + 1}/{total_batches}")
                    
                    # Fetch quotes for this batch
                    batch_result = await quote_client.get_quotes_concurrent(batch_symbols)
                    batch_lengths.append(len(batch_result) if batch_result else 0)
                    logger.info(f"📊 Batch {batch_num + 1} returned: {batch_lengths[-1]} results (sent {len(batch_symbols)} symbols)")
                    
                    all_quote_results.extend(batch_result)
                    
                    # Wait if not last batch (rate limiting: 180 requests per 53s = ~196 req/min, 2% buffer)
                    if batch_num < total_batches - 1:
                        await asyncio.sleep(53)  # 53 seconds for optimal speed with safety margin
                
                logger.info(f"📊 Quote API responses (per batch): {batch_lengths}")
                
                # Step 4: Process results (80% progress)
                active_jobs[job_id].message = "Processing quote results..."
                active_jobs[job_id].progress = 80
                
                logger.info(f"📊 Total API results before flattening: {len(all_quote_results)}")
                
                flattened_quote_result = await flatten_quote_result_list(all_quote_results)
                logger.info(f"📊 Flattened results: {len(flattened_quote_result)}")
                
                quote_ohlc = await fetch_ohlc_from_quote_result(flattened_quote_result)
                logger.info(f"📊 Quote OHLC final: {len(quote_ohlc)}")
                
                # Step 5: Update DataFrame (85% progress)
                active_jobs[job_id].message = "Calculating prices..."
                active_jobs[job_id].progress = 85
                
                logger.info(f"📊 Mapping: {len(quote_ohlc)} quotes → {len(valid_indices)} positions (DataFrame has {len(df)} rows)")
                
                df = await update_df_with_quote_ohlc(df, quote_ohlc, valid_indices)
                
                # Step 6: Write to Google Sheet (90% progress)
                active_jobs[job_id].message = "Writing to Google Sheet..."
                active_jobs[job_id].progress = 90
                
                write_success = await write_quote_ohlc_to_gsheet(
                    df,
                    os.getenv("sheet_id"),
                    os.getenv("sheet_gid")
                )
                
                # Complete (100% progress)
                active_jobs[job_id].status = "completed"
                active_jobs[job_id].progress = 100
                active_jobs[job_id].message = "Quotes fetched and Google Sheet updated successfully"
                active_jobs[job_id].completed_at = get_ist_now().isoformat()
                active_jobs[job_id].result = {"status": "success", "stocks_processed": total_symbols}
                
                logger.info(f"[Job {job_id}] GET QUOTES completed successfully")
                
                # Broadcast completion to all WebSocket clients
                await ws_manager.broadcast_message({
                    "type": "job_completed",
                    "job": asdict(active_jobs[job_id])
                })
                
            except Exception as e:
                logger.error(f"[Job {job_id}] GET QUOTES failed: {e}")
                active_jobs[job_id].status = "failed"
                active_jobs[job_id].progress = 0
                active_jobs[job_id].message = f"Failed to fetch quotes: {str(e)}"
                active_jobs[job_id].error = str(e)
                active_jobs[job_id].completed_at = get_ist_now().isoformat()
                
                # Broadcast failure to WebSocket clients
                await ws_manager.broadcast_message({
                    "type": "job_failed",
                    "job": asdict(active_jobs[job_id])
                })
        
        # Add task to background
        background_tasks.add_task(run_get_quotes_background)
        
        logger.info(f"[Job {job_id}] GET QUOTES started in background")
        
        return {
            "success": True,
            "job_id": job_id,
            "message": "Quote fetching started in background (3-4 minutes)",
            "estimated_time": "3-4 minutes"
        }
        
    except Exception as e:
        logger.error(f"Error starting GET QUOTES background task: {e}")
        return {
            "success": False,
            "message": f"Failed to start quote fetching: {str(e)}"
        }


@app.get("/api/job_status/{job_id}")
async def get_job_status(job_id: str):
    """Get status of a background job by job_id"""
    try:
        job = active_jobs.get(job_id)
        
        if not job:
            return {
                "success": False,
                "message": "Job not found or expired",
                "job_id": job_id
            }
        
        return {
            "success": True,
            "job": asdict(job)
        }
        
    except Exception as e:
        logger.error(f"Error getting job status for {job_id}: {e}")
        return {
            "success": False,
            "message": f"Error retrieving job status: {str(e)}"
        }

@app.get("/api/active_jobs")
async def get_active_jobs():
    """Get all active jobs (for debugging/monitoring)"""
    try:
        return {
            "success": True,
            "total_jobs": len(active_jobs),
            "jobs": {job_id: asdict(job) for job_id, job in active_jobs.items()}
        }
    except Exception as e:
        logger.error(f"Error getting active jobs: {e}")
        return {
            "success": False,
            "message": str(e)
        }

# @app.get("/api/nse_cm_scrip_data")
# async def get_nse_cm_scrip_data():
#     """
#     Extract nse_cm-v1.csv from master scrip files, load as DataFrame, and return head
#     Uses authentication from kotak_session.json
#     """
#     try:
#         # Load session data from kotak_session.json
#         session_file = "kotak_session.json"
        
#         if not os.path.exists(session_file):
#             logger.error("Session file not found - please authenticate first")
#             return {
#                 "success": False,
#                 "message": "No active session - please verify TOTP first"
#             }
        
#         # Read session file
#         async with aiofiles.open(session_file, 'r') as f:
#             content = await f.read()
#             session_data = json.loads(content)
        
#         # Extract access token
#         access_token = session_data.get('access_token')
        
#         if not access_token:
#             logger.error("Access token not found in session")
#             return {
#                 "success": False,
#                 "message": "Invalid session data - missing access token"
#             }
        
#         # Step 1: Get file paths
#         url = "https://gw-napi.kotaksecurities.com/Files/1.0/masterscrip/v2/file-paths"
#         headers = {
#             'accept': '*/*',
#             'Authorization': f'Bearer {access_token}'
#         }
        
#         logger.info("📡 Step 1: Fetching master scrip file paths...")
        
#         async with httpx.AsyncClient(verify=False, timeout=30, follow_redirects=True) as client:
#             response = await client.get(url, headers=headers)
            
#             if response.status_code != 200:
#                 logger.error(f"Failed to fetch file paths. Status: {response.status_code}")
#                 return {
#                     "success": False,
#                     "message": f"API returned status {response.status_code}"
#                 }
            
#             data = response.json()
#             file_paths = data.get('data', {}).get('filesPaths', [])
            
#             # Step 2: Find nse_cm-v1.csv URL
#             nse_cm_url = None
#             for path in file_paths:
#                 if 'nse_cm-v1.csv' in path:
#                     nse_cm_url = path
#                     break
            
#             if not nse_cm_url:
#                 logger.error("nse_cm-v1.csv not found in file paths")
#                 return {
#                     "success": False,
#                     "message": "nse_cm-v1.csv not found in available files"
#                 }
            
#             logger.info(f"📍 Found nse_cm-v1.csv: {nse_cm_url}")
            
#             # Step 3: Download and load CSV as DataFrame
#             logger.info("📥 Downloading nse_cm-v1.csv...")
#             csv_response = await client.get(nse_cm_url)
            
#             if csv_response.status_code != 200:
#                 logger.error(f"Failed to download CSV. Status: {csv_response.status_code}")
#                 return {
#                     "success": False,
#                     "message": f"Failed to download CSV file"
#                 }
            
#             # Load into pandas DataFrame
#             logger.info("📊 Loading CSV into pandas DataFrame...")
#             df = pd.read_csv(io.StringIO(csv_response.text))
            
#             # Get DataFrame info
#             total_rows = len(df)
#             columns = df.columns.tolist()
            
#             logger.info(f"✅ Loaded nse_cm DataFrame: {total_rows} rows, {len(columns)} columns")
            
#             # Print head to console
#             print("\n" + "="*80)
#             print("NSE CM MASTER SCRIP DATA - HEAD (First 10 rows)")
#             print("="*80)
#             print(df.head(10).to_string())
#             print("="*80)
#             print(f"\nColumns: {columns}")
#             print(f"Total Rows: {total_rows}")
#             print("="*80 + "\n")
            
#             # Write entire DataFrame to Google Sheet
#             logger.info("🔄 Writing NSE CM data to Google Sheet...")
#             sheet_id = "1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM"
#             gid = "1765483913"  # nse_cm_neo sheet
            
#             try:
#                 import gspread
#                 from oauth2client.service_account import ServiceAccountCredentials
                
#                 # Set up credentials
#                 scope = [
#                     'https://spreadsheets.google.com/feeds',
#                     'https://www.googleapis.com/auth/drive'
#                 ]
#                 creds_file = 'google_sheets_credentials.json'
                
#                 if not os.path.exists(creds_file):
#                     logger.error("❌ Google Sheets credentials file not found")
#                     return {
#                         "success": True,
#                         "file_url": nse_cm_url,
#                         "total_rows": total_rows,
#                         "columns": columns,
#                         "message": f"NSE CM data loaded ({total_rows} rows) but NOT written to Google Sheet (credentials missing)"
#                     }
                
#                 # Authenticate with Google Sheets
#                 creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
#                 gsheet_client = gspread.authorize(creds)
#                 logger.info("✅ Authenticated with Google Sheets API")
                
#                 # Open spreadsheet
#                 spreadsheet = gsheet_client.open_by_key(sheet_id)
                
#                 # Find worksheet by gid
#                 worksheet = None
#                 for sheet in spreadsheet.worksheets():
#                     if str(sheet.id) == str(gid):
#                         worksheet = sheet
#                         break
                
#                 if worksheet is None:
#                     logger.error(f"⚠️ GID {gid} not found")
#                     return {
#                         "success": True,
#                         "total_rows": total_rows,
#                         "message": f"Data loaded but worksheet GID {gid} not found"
#                     }
                
#                 logger.info(f"✅ Found worksheet: {worksheet.title}")
                
#                 # Prepare data (convert DataFrame to list of lists)
#                 import numpy as np
#                 data = [df.columns.tolist()] + df.values.tolist()
                
#                 # Replace NaN with empty string
#                 data = [['' if (isinstance(cell, float) and np.isnan(cell)) else cell for cell in row] for row in data]
                
#                 logger.info(f"📊 Prepared {len(data)} rows for upload (including header)")
                
#                 # Clear existing data
#                 worksheet.clear()
#                 logger.info("🗑️ Cleared existing worksheet data")
                
#                 # Write data in batches to avoid API limits (Google Sheets has 10MB limit per request)
#                 batch_size = 5000
#                 total_batches = (len(data) + batch_size - 1) // batch_size
                
#                 logger.info(f"📤 Writing data in {total_batches} batch(es)...")
                
#                 for batch_num in range(total_batches):
#                     start_idx = batch_num * batch_size
#                     end_idx = min(start_idx + batch_size, len(data))
#                     batch_data = data[start_idx:end_idx]
                    
#                     # Calculate range
#                     start_row = start_idx + 1
#                     end_row = end_idx
#                     range_name = f'A{start_row}'
                    
#                     worksheet.update(range_name, batch_data)
#                     logger.info(f"✅ Batch {batch_num + 1}/{total_batches} written ({end_idx - start_idx} rows)")
                
#                 logger.info(f"✅ Successfully wrote {total_rows} rows to Google Sheet")
                
#                 return {
#                     "success": True,
#                     "file_url": nse_cm_url,
#                     "total_rows": total_rows,
#                     "columns": columns,
#                     "google_sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={gid}",
#                     "message": f"NSE CM data loaded ({total_rows} rows) and written to Google Sheet successfully"
#                 }
                
#             except ImportError:
#                 logger.error("❌ Missing gspread/oauth2client packages")
#                 return {
#                     "success": True,
#                     "total_rows": total_rows,
#                     "message": f"Data loaded but Google Sheets write failed (missing packages)"
#                 }
#             except Exception as write_error:
#                 logger.error(f"❌ Failed to write to Google Sheet: {write_error}")
#                 return {
#                     "success": True,
#                     "file_url": nse_cm_url,
#                     "total_rows": total_rows,
#                     "columns": columns,
#                     "message": f"NSE CM data loaded ({total_rows} rows) but failed to write to Google Sheet: {str(write_error)}"
#                 }
                
#     except Exception as e:
#         logger.error(f"Error fetching NSE CM scrip data: {e}")
#         return {
#             "success": False,
#             "message": f"Error: {str(e)}"
#         }
        

@app.get("/status")
async def status():
    global sme_task, equities_task, ai_processing_active
    return {
        "sme_task_running": sme_task is not None and not sme_task.done(),
        "equities_task_running": equities_task is not None and not equities_task.done(),
        "dashboard_active": True,
        "ai_processing_active": ai_processing_active
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",port=5000)
