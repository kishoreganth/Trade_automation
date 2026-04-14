from nsepython import *
import asyncio
# import nsepythonserver
import csv
import requests
import os
import json
import pandas as pd
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
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
from bse import BSE
import fitz
import base64
from openai import AsyncOpenAI
from async_ocr_from_image import download_pdf_async
from neo_main_login import main as neo_main_login
from place_order import main as place_order_main
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Auto fetch flag - controls both backend scheduled task and frontend UI
# Set AUTO_FETCH_ENABLED=true in .env to enable auto fetch
AUTO_FETCH_ENABLED = os.getenv("AUTO_FETCH_ENABLED", "false").lower() == "true"

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

def parse_datetime_ist(datetime_str: str) -> Optional[datetime]:
    """
    Parse datetime string and ensure it's IST-aware
    Handles: naive, UTC, other timezones - always returns IST
    
    Args:
        datetime_str: ISO format datetime string
        
    Returns:
        IST-aware datetime object, or None if parsing fails
    """
    if not datetime_str:
        return None
    
    try:
        # Parse ISO format, handle 'Z' suffix for UTC
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        
        if dt.tzinfo is None:
            # Naive datetime - assume IST
            return IST.localize(dt)
        else:
            # Has timezone - convert to IST
            return dt.astimezone(IST)
    except Exception as e:
        logger.error(f"Failed to parse datetime '{datetime_str}': {e}")
        return None

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
    
    # Load scheduled fetch config from config.json (single source of truth)
    load_scheduled_fetch_config_sync()
    
    # Load Google Sheets data asynchronously during startup
    logger.info("Loading Google Sheets data...")
    await load_watchlist_chat_ids()
    logger.info("Google Sheets data loaded successfully")
    
    # Load sector map BEFORE init_db so migration can backfill sectors
    await asyncio.to_thread(load_sector_map)
    if not bse_sector_map and not nse_sector_map and not sector_map:
        logger.warning("Sector map empty on first load. Retrying in 2s (file may still be mounting)...")
        await asyncio.sleep(2)
        await asyncio.to_thread(load_sector_map)
    if not bse_sector_map and not nse_sector_map and not sector_map:
        logger.warning("Sector map still empty after retry. Sectors will be blank until file is available.")
    
    # Initialize database (after sector_map loaded — one-time migration uses it)
    await init_db()
    logger.info("Dashboard database initialized")
    
    logger.info("PyMuPDF (fitz) ready for PDF extraction — no OCR model needed")
    
    # Start all background tasks in parallel using asyncio.create_task
    # sme_task = asyncio.create_task(run_periodic_task_sme())
    equities_task = asyncio.create_task(run_periodic_task_equities())
    cleanup_task = asyncio.create_task(run_periodic_cleanup())
    
    # Only start scheduled fetch task if AUTO_FETCH_ENABLED is true
    if AUTO_FETCH_ENABLED:
        scheduled_quotes_task = asyncio.create_task(run_scheduled_fetch_quotes())
        logger.info("✅ All background tasks started: Equities, Periodic Cleanup, and Scheduled Fetch Quotes")
        logger.info(f"📅 Scheduled fetch quotes: {SCHEDULED_FETCH_CONFIG['hour']:02d}:{SCHEDULED_FETCH_CONFIG['minute']:02d}:{SCHEDULED_FETCH_CONFIG['second']:02d} IST (Mon-Fri)")
    else:
        logger.info("✅ Background tasks started: Equities, Periodic Cleanup")
        logger.info("⚠️ Auto fetch DISABLED (set AUTO_FETCH_ENABLED=true in .env to enable)")
    
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
    
    if scheduled_quotes_task and not scheduled_quotes_task.done():
        scheduled_quotes_task.cancel()
        try:
            await scheduled_quotes_task
        except asyncio.CancelledError:
            print("Scheduled quotes task was cancelled")
            logger.info("Scheduled quotes task was cancelled")
    
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

# Stocks master sync on every init_db (idempotent). Policy:
#   "always" — run insert-missing + backfills each startup (recovers interrupted migrations).
#   "empty_only" — run only when stocks table has zero rows.
#   "below_threshold" — run while COUNT(stocks) < STOCKS_SYNC_THRESHOLD (e.g. partial load).
STOCKS_SYNC_POLICY = os.getenv("STOCKS_SYNC_POLICY", "always")
STOCKS_SYNC_THRESHOLD = int(os.getenv("STOCKS_SYNC_THRESHOLD", "1000"))

# Scrip master from Google Sheet for exchange token lookup
NSE_CM_NEO_GID = "1765483913"
BSE_CM_NEO_GID = "895275415"
_nse_token_cache: Dict[str, int] = {}
_bse_token_cache: Dict[str, int] = {}


async def _fetch_nse_token_map() -> Dict[str, int]:
    """Fetch nse_cm_neo sheet → {SYMBOL: exchange_token}. Cached in-memory after first call."""
    global _nse_token_cache
    if _nse_token_cache:
        return _nse_token_cache
    sheet_id = os.getenv("sheet_id", "1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM")
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={NSE_CM_NEO_GID}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Failed to fetch nse_cm_neo sheet: HTTP {resp.status}")
                    return {}
                csv_text = await resp.text()
        import io
        df = pd.read_csv(io.StringIO(csv_text))
        df.columns = [c.strip() for c in df.columns]
        for _, row in df.iterrows():
            sym_name = str(row.get("pSymbolName", "")).strip()
            token = row.get("pSymbol")
            if not sym_name or pd.isna(token):
                continue
            clean_sym = sym_name.split("-")[0].strip().upper()
            try:
                _nse_token_cache[clean_sym] = int(float(token))
            except (ValueError, TypeError):
                continue
        logger.info(f"Loaded {len(_nse_token_cache)} NSE symbol→token mappings from nse_cm_neo sheet")
    except Exception as e:
        logger.error(f"Error fetching nse_cm_neo token map: {e}")
    return _nse_token_cache


async def _fetch_bse_token_map() -> Dict[str, int]:
    """Fetch bse_cm_neo sheet → {SYMBOL: exchange_token}. Cached in-memory after first call."""
    global _bse_token_cache
    if _bse_token_cache:
        return _bse_token_cache
    sheet_id = os.getenv("sheet_id", "1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM")
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={BSE_CM_NEO_GID}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Failed to fetch bse_cm_neo sheet: HTTP {resp.status}")
                    return {}
                csv_text = await resp.text()
        import io
        df = pd.read_csv(io.StringIO(csv_text))
        df.columns = [c.strip() for c in df.columns]
        for _, row in df.iterrows():
            sym_name = str(row.get("pSymbolName", "")).strip()
            trd_sym = str(row.get("pTrdSymbol", "")).strip()
            token = row.get("pSymbol")
            if not sym_name or pd.isna(token):
                continue
            clean_sym = sym_name.split("-")[0].strip().upper()
            clean_trd = trd_sym.split("-")[0].strip().upper() if trd_sym else ""
            try:
                tok_int = int(float(token))
                _bse_token_cache[clean_sym] = tok_int
                if clean_trd and clean_trd != clean_sym:
                    _bse_token_cache[clean_trd] = tok_int
            except (ValueError, TypeError):
                continue
        logger.info(f"Loaded {len(_bse_token_cache)} BSE symbol→token mappings from bse_cm_neo sheet")
    except Exception as e:
        logger.error(f"Error fetching bse_cm_neo token map: {e}")
    return _bse_token_cache


async def _check_session_valid() -> bool:
    """Quick check if kotak_session.json exists and is not expired."""
    session_file = "kotak_session.json"
    if not os.path.exists(session_file):
        return False
    try:
        async with aiofiles.open(session_file, 'r') as f:
            sess = json.loads(await f.read())
        exp = parse_datetime_ist(sess.get("expires_at", ""))
        return exp is not None and get_ist_now() < exp
    except Exception:
        return False


async def _auto_fetch_cmp_for_stock(symbol: str, fy_eps: float, exchange: str = "NSE") -> Dict:
    """Auto-fetch CMP for a single stock after extraction. Returns {cmp, pe, error}."""
    result = {"cmp": None, "pe": None, "error": None}
    if not fy_eps or fy_eps <= 0:
        result["error"] = "FY EPS not positive — cannot compute PE"
        return result

    if not await _check_session_valid():
        result["error"] = "No active session — verify TOTP to auto-fetch CMP"
        return result

    try:
        is_bse = exchange.upper() == "BSE"
        if is_bse:
            token = symbol
        else:
            token_map = await _fetch_nse_token_map()
            token = token_map.get(symbol)
            if not token:
                result["error"] = f"No instrument token for {symbol} (NSE)"
                return result

        from get_quote import get_quotes_with_rate_limit, flatten_quote_result_list
        prefix = "bse_cm" if is_bse else "nse_cm"
        sym_str = f"{prefix}|{token}"
        raw = await get_quotes_with_rate_limit([sym_str], requests_per_minute=190)
        flattened = await flatten_quote_result_list(raw)

        cmp = None
        for q in flattened:
            if q.get("error"):
                continue
            close_price = q.get("ohlc", {}).get("close")
            if close_price:
                cmp_raw = float(close_price)
                cmp = cmp_raw / 100 if cmp_raw > 100000 else cmp_raw
                break

        if not cmp:
            result["error"] = f"CMP not available from API for {symbol}"
            return result

        pe = round(cmp / fy_eps, 2)
        now_iso = get_ist_now().isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE quarterly_results SET cmp = ?, pe = ?, cmp_updated_at = ?
                   WHERE id = (
                       SELECT id FROM quarterly_results
                       WHERE stock_symbol = ? AND quarter != 'FY'
                       ORDER BY financial_year DESC, quarter DESC LIMIT 1
                   )""",
                (cmp, pe, now_iso, symbol)
            )
            await db.commit()

        result["cmp"] = round(cmp, 2)
        result["pe"] = pe
        logger.info(f"Auto CMP for {symbol}: ₹{cmp:.2f} | PE: {pe}")
        return result

    except Exception as e:
        logger.warning(f"Auto CMP fetch failed for {symbol}: {e}")
        result["error"] = str(e)
        return result


# Default admin: change DEFAULT_ADMIN_PASSWORD and deploy – existing server admin will be updated on startup
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Arixjhifi@007"  # Change this; server admin password will sync on next deploy
OLD_DEFAULT_ADMIN_PASSWORD = "admin123"  # Used only to detect and migrate old default

class MessageData(BaseModel):
    chat_id: str
    message: str
    timestamp: Optional[str] = None
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    description: Optional[str] = None
    file_url: Optional[str] = None
    option: Optional[str] = None
    sector: Optional[str] = None
    exchange: Optional[str] = None  # NSE or BSE

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


async def _should_run_stocks_sync(db) -> bool:
    cursor = await db.execute("SELECT COUNT(*) FROM stocks")
    n = (await cursor.fetchone())[0]
    p = (STOCKS_SYNC_POLICY or "always").strip().lower()
    if p == "always":
        return True
    if p == "empty_only":
        return n == 0
    if p in ("below_threshold", "below", "threshold"):
        return n < STOCKS_SYNC_THRESHOLD
    logger.warning("Unknown STOCKS_SYNC_POLICY=%r; using always", STOCKS_SYNC_POLICY)
    return True


async def _sync_stocks_master_from_sources(db) -> None:
    """Idempotent: add missing symbols from messages + quarterly_results, backfill stock_id and sector."""
    import time as _time
    sync_start = _time.time()
    now_iso = get_ist_now().isoformat()
    cursor = await db.execute("SELECT COUNT(*) FROM stocks")
    before = (await cursor.fetchone())[0]
    logger.info("📦 Stocks master sync STARTED (existing=%s, policy=%s)", before, STOCKS_SYNC_POLICY)

    # Step 1: Insert missing symbols from messages
    logger.info("  [1/4] Syncing stocks from messages...")
    cursor = await db.execute(
        """
        INSERT INTO stocks (symbol, company_name, exchange, sector, is_active, added_at, updated_at)
        SELECT
            UPPER(TRIM(m.symbol)),
            (SELECT m2.company_name FROM messages m2
             WHERE UPPER(TRIM(m2.symbol)) = UPPER(TRIM(m.symbol)) AND m2.company_name IS NOT NULL AND TRIM(m2.company_name) != ''
             ORDER BY m2.id DESC LIMIT 1),
            (SELECT m3.exchange FROM messages m3
             WHERE UPPER(TRIM(m3.symbol)) = UPPER(TRIM(m.symbol)) AND m3.exchange IS NOT NULL AND TRIM(m3.exchange) != ''
             ORDER BY m3.id DESC LIMIT 1),
            (SELECT m4.sector FROM messages m4
             WHERE UPPER(TRIM(m4.symbol)) = UPPER(TRIM(m.symbol)) AND m4.sector IS NOT NULL AND TRIM(m4.sector) != ''
             ORDER BY m4.id DESC LIMIT 1),
            1, ?, ?
        FROM messages m
        WHERE m.symbol IS NOT NULL AND TRIM(m.symbol) != ''
        AND NOT EXISTS (SELECT 1 FROM stocks s WHERE s.symbol = UPPER(TRIM(m.symbol)))
        GROUP BY UPPER(TRIM(m.symbol))
        """,
        (now_iso, now_iso),
    )
    from_messages = cursor.rowcount
    logger.info("  [1/4] Done — %s new stocks from messages", from_messages)

    # Step 2: Insert missing symbols from quarterly_results
    logger.info("  [2/4] Syncing stocks from quarterly_results...")
    cursor = await db.execute(
        """
        INSERT INTO stocks (symbol, company_name, exchange, sector, is_active, added_at, updated_at)
        SELECT
            UPPER(TRIM(qr.stock_symbol)),
            (SELECT q2.company_name FROM quarterly_results q2
             WHERE UPPER(TRIM(q2.stock_symbol)) = UPPER(TRIM(qr.stock_symbol)) AND q2.company_name IS NOT NULL AND TRIM(q2.company_name) != ''
             ORDER BY q2.id DESC LIMIT 1),
            (SELECT q3.exchange FROM quarterly_results q3
             WHERE UPPER(TRIM(q3.stock_symbol)) = UPPER(TRIM(qr.stock_symbol)) AND q3.exchange IS NOT NULL AND TRIM(q3.exchange) != ''
             ORDER BY q3.id DESC LIMIT 1),
            NULL,
            1, ?, ?
        FROM quarterly_results qr
        WHERE qr.stock_symbol IS NOT NULL AND TRIM(qr.stock_symbol) != ''
        AND NOT EXISTS (SELECT 1 FROM stocks s WHERE s.symbol = UPPER(TRIM(qr.stock_symbol)))
        GROUP BY UPPER(TRIM(qr.stock_symbol))
        """,
        (now_iso, now_iso),
    )
    from_qr = cursor.rowcount
    logger.info("  [2/4] Done — %s new stocks from quarterly_results", from_qr)

    # Step 3: Backfill quarterly_results.stock_id
    logger.info("  [3/4] Backfilling quarterly_results.stock_id...")
    cursor = await db.execute(
        """
        UPDATE quarterly_results
        SET stock_id = (
            SELECT id FROM stocks WHERE stocks.symbol = UPPER(TRIM(quarterly_results.stock_symbol))
        )
        WHERE stock_id IS NULL
        AND EXISTS (
            SELECT 1 FROM stocks WHERE stocks.symbol = UPPER(TRIM(quarterly_results.stock_symbol))
        )
        """
    )
    stock_id_filled = cursor.rowcount
    logger.info("  [3/4] Done — %s quarterly_results rows linked to stock_id", stock_id_filled)

    # Step 4: Fill sector from xlsx map where still empty
    logger.info("  [4/4] Backfilling sectors from xlsx map...")
    sector_filled = 0
    if sector_map:
        cursor = await db.execute(
            "SELECT symbol FROM stocks WHERE sector IS NULL OR TRIM(sector) = ''"
        )
        missing_sector_rows = await cursor.fetchall()
        for (sym,) in missing_sector_rows:
            sec = sector_map.get(sym)
            if sec:
                await db.execute(
                    "UPDATE stocks SET sector = ?, updated_at = ? WHERE symbol = ?",
                    (sec, now_iso, sym),
                )
                sector_filled += 1
    logger.info("  [4/4] Done — %s stocks got sector backfilled", sector_filled)

    cursor = await db.execute("SELECT COUNT(*) FROM stocks")
    after = (await cursor.fetchone())[0]
    elapsed = _time.time() - sync_start
    logger.info(
        "✅ Stocks master sync COMPLETED in %.2fs — before=%s after=%s (new_from_messages=%s new_from_qr=%s stock_id_linked=%s sectors_filled=%s)",
        elapsed, before, after, from_messages, from_qr, stock_id_filled, sector_filled,
    )


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
        
        # Master stocks table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE NOT NULL,
                company_name TEXT,
                exchange TEXT,
                sector TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_stocks_symbol ON stocks(symbol)")
        # Migration: add token columns to stocks
        for col, col_type in [
            ("nse_token", "INTEGER"),
            ("bse_token", "INTEGER"),
            ("isin", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE stocks ADD COLUMN {col} {col_type}")
            except Exception:
                pass
        
        # Create quarterly_results table (Analytics - PE Analysis)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quarterly_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_symbol TEXT NOT NULL,
                company_name TEXT,
                quarter TEXT NOT NULL,
                financial_year TEXT NOT NULL,
                period_ended TEXT,
                eps_basic_standalone REAL,
                eps_diluted_standalone REAL,
                eps_basic_consolidated REAL,
                eps_diluted_consolidated REAL,
                fy_eps_basic_standalone REAL,
                fy_eps_diluted_standalone REAL,
                fy_eps_basic_consolidated REAL,
                fy_eps_diluted_consolidated REAL,
                fy_eps_formula_standalone TEXT,
                fy_eps_formula_consolidated TEXT,
                standalone_data TEXT,
                consolidated_data TEXT,
                raw_ai_response TEXT,
                source_pdf_url TEXT,
                source_message_id INTEGER,
                exchange TEXT,
                units TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(stock_symbol, quarter, financial_year),
                FOREIGN KEY (source_message_id) REFERENCES messages(id)
            )
        """)
        # Add new columns if upgrading from older schema
        for col, col_type in [
            ("fy_eps_basic_standalone", "REAL"),
            ("fy_eps_diluted_standalone", "REAL"),
            ("fy_eps_basic_consolidated", "REAL"),
            ("fy_eps_diluted_consolidated", "REAL"),
            ("fy_eps_formula_standalone", "TEXT"),
            ("fy_eps_formula_consolidated", "TEXT"),
            ("stock_id", "INTEGER REFERENCES stocks(id)"),
            ("cmp", "REAL"),
            ("pe", "REAL"),
            ("cmp_updated_at", "TEXT"),
            ("cumulative_eps_basic_standalone", "REAL"),
            ("cumulative_eps_diluted_standalone", "REAL"),
            ("cumulative_eps_basic_consolidated", "REAL"),
            ("cumulative_eps_diluted_consolidated", "REAL"),
            ("valuation", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE quarterly_results ADD COLUMN {col} {col_type}")
            except Exception:
                pass
        await db.execute("CREATE INDEX IF NOT EXISTS idx_qr_symbol ON quarterly_results(stock_symbol)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_qr_quarter_fy ON quarterly_results(quarter, financial_year)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_qr_stock_id ON quarterly_results(stock_id)")

        # Create pe_formulas table for custom FY EPS estimation formulas
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pe_formulas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                q1_expr TEXT NOT NULL DEFAULT 'Q1*4',
                q2_expr TEXT NOT NULL DEFAULT '(Q1+Q2)*2',
                q3_expr TEXT NOT NULL DEFAULT '(Q1+Q2+Q3)*4/3',
                q4_expr TEXT NOT NULL DEFAULT 'FY',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            INSERT OR IGNORE INTO pe_formulas (name, q1_expr, q2_expr, q3_expr, q4_expr, is_default, created_at, updated_at)
            VALUES ('Default', 'Q1*4', '(Q1+Q2)*2', '(Q1+Q2+Q3)*4/3', 'FY', 1, datetime('now'), datetime('now'))
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
        
        # Create scheduled_fetch_config table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_fetch_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                enabled INTEGER NOT NULL DEFAULT 1,
                hour INTEGER NOT NULL DEFAULT 12,
                minute INTEGER NOT NULL DEFAULT 40,
                second INTEGER NOT NULL DEFAULT 0,
                weekdays_only INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Initialize default config if not exists
        cursor = await db.execute("SELECT COUNT(*) FROM scheduled_fetch_config")
        config_count = (await cursor.fetchone())[0]
        if config_count == 0:
            await db.execute("""
                INSERT INTO scheduled_fetch_config (enabled, hour, minute, second, weekdays_only, updated_at)
                VALUES (1, 12, 40, 0, 1, ?)
            """, (get_ist_now().isoformat(),))
            logger.info("Initialized default scheduled fetch config: 12:40:00 IST (Mon-Fri)")
        
        # Check if option column exists, if not add it
        cursor = await db.execute("PRAGMA table_info(messages)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'option' not in column_names:
            logger.info("Adding option column to existing database")
            await db.execute("ALTER TABLE messages ADD COLUMN option TEXT")
        
        if 'sector' not in column_names:
            logger.info("Adding sector column to existing database")
            await db.execute("ALTER TABLE messages ADD COLUMN sector TEXT")
        
        if 'exchange' not in column_names:
            logger.info("Adding exchange column to existing database")
            await db.execute("ALTER TABLE messages ADD COLUMN exchange TEXT")
            await db.execute("UPDATE messages SET exchange = ? WHERE exchange IS NULL", ("NSE",))
        
        # Create default admin user if no users exist
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        user_count = (await cursor.fetchone())[0]
        
        if user_count == 0:
            password_hash = hashlib.sha256(DEFAULT_ADMIN_PASSWORD.encode()).hexdigest()
            await db.execute("""
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
            """, (DEFAULT_ADMIN_USERNAME, password_hash, get_ist_now().isoformat()))
            logger.info(f"Created default admin user - Username: {DEFAULT_ADMIN_USERNAME}, Password: (set)")
        else:
            # Sync server admin password when code default changed (e.g. after deploy)
            old_hash = hashlib.sha256(OLD_DEFAULT_ADMIN_PASSWORD.encode()).hexdigest()
            new_hash = hashlib.sha256(DEFAULT_ADMIN_PASSWORD.encode()).hexdigest()
            if new_hash != old_hash:
                cursor = await db.execute(
                    "SELECT id FROM users WHERE username = ? AND password_hash = ?",
                    (DEFAULT_ADMIN_USERNAME, old_hash)
                )
                if await cursor.fetchone():
                    await db.execute(
                        "UPDATE users SET password_hash = ? WHERE username = ?",
                        (new_hash, DEFAULT_ADMIN_USERNAME)
                    )
                    logger.info(f"Updated default admin password to new default (deploy sync)")
        
        if await _should_run_stocks_sync(db):
            await _sync_stocks_master_from_sources(db)

        await db.commit()
    logger.info("Database initialized with authentication tables")


async def get_or_create_stock(db, symbol: str, company_name: str = None, exchange: str = None, sector: str = None) -> int:
    """Get existing stock_id or auto-insert a new stock. Returns stocks.id."""
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("get_or_create_stock: empty symbol")
    cursor = await db.execute("SELECT id, company_name, exchange FROM stocks WHERE symbol = ?", (symbol,))
    row = await cursor.fetchone()
    now_iso = get_ist_now().isoformat()
    if row:
        stock_id = row[0]
        updates = []
        params = []
        if company_name and not row[1]:
            updates.append("company_name = ?")
            params.append(company_name)
        if exchange and not row[2]:
            updates.append("exchange = ?")
            params.append(exchange)
        if updates:
            updates.append("updated_at = ?")
            params.append(now_iso)
            params.append(stock_id)
            await db.execute(f"UPDATE stocks SET {', '.join(updates)} WHERE id = ?", params)
        return stock_id
    cursor = await db.execute(
        "INSERT INTO stocks (symbol, company_name, exchange, sector, is_active, added_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
        (symbol, company_name, exchange, sector, now_iso, now_iso)
    )
    logger.info(f"Auto-inserted new stock: {symbol} (exchange={exchange})")
    return cursor.lastrowid


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

# Separate logger for scheduled fetch events (start/completion only)
scheduled_fetch_logger = logging.getLogger('scheduled_fetch')
scheduled_fetch_logger.setLevel(logging.INFO)
scheduled_fetch_logger.propagate = False  # Don't propagate to root logger

# File handler for scheduled fetch log
scheduled_fetch_handler = logging.FileHandler('scheduled_fetch.log', encoding='utf-8')
scheduled_fetch_handler.setLevel(logging.INFO)
scheduled_fetch_formatter = logging.Formatter('%(asctime)s - %(message)s')
scheduled_fetch_handler.setFormatter(scheduled_fetch_formatter)
scheduled_fetch_logger.addHandler(scheduled_fetch_handler)

# Store task references globally
sme_task = None
equities_task = None
cleanup_task = None
scheduled_quotes_task = None  # Scheduled fetch quotes task
ai_processing_active = False  # Flag to pause background tasks during AI processing

# Scheduled fetch quotes configuration (loaded from config.json - single source of truth)
CONFIG_FILE = "config.json"
SCHEDULED_FETCH_CONFIG = {
    "enabled": True,
    "hour": 12,
    "minute": 40,
    "second": 0,
    "weekdays_only": True
}

def load_scheduled_fetch_config_sync():
    """Load scheduled fetch config from config.json file (synchronous)"""
    global SCHEDULED_FETCH_CONFIG
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                scheduled_config = config_data.get('scheduled_fetch', {})
                SCHEDULED_FETCH_CONFIG = {
                    "enabled": scheduled_config.get("enabled", True),
                    "hour": scheduled_config.get("hour", 12),
                    "minute": scheduled_config.get("minute", 40),
                    "second": scheduled_config.get("second", 0),
                    "weekdays_only": scheduled_config.get("weekdays_only", True)
                }
                logger.info(f"✅ Loaded scheduled fetch config from {CONFIG_FILE}: {SCHEDULED_FETCH_CONFIG['hour']:02d}:{SCHEDULED_FETCH_CONFIG['minute']:02d}:{SCHEDULED_FETCH_CONFIG['second']:02d} IST")
            return True
        else:
            logger.warning(f"⚠️ {CONFIG_FILE} not found, using defaults: {SCHEDULED_FETCH_CONFIG['hour']:02d}:{SCHEDULED_FETCH_CONFIG['minute']:02d}:{SCHEDULED_FETCH_CONFIG['second']:02d} IST")
            return False
    except Exception as e:
        logger.error(f"❌ Error loading {CONFIG_FILE}: {e}")
        return False

async def load_scheduled_fetch_config():
    """Load scheduled fetch config from config.json file (async wrapper)"""
    await asyncio.to_thread(load_scheduled_fetch_config_sync)

def save_scheduled_fetch_config(config: Dict) -> bool:
    """Save scheduled fetch config to config.json file"""
    try:
        # Load existing config or create new
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        else:
            config_data = {}
        
        # Update scheduled_fetch section
        config_data['scheduled_fetch'] = {
            "enabled": config.get("enabled", True),
            "hour": config.get("hour", 12),
            "minute": config.get("minute", 40),
            "second": config.get("second", 0),
            "weekdays_only": config.get("weekdays_only", True)
        }
        
        # Save to file
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        
        # Update global config
        global SCHEDULED_FETCH_CONFIG
        SCHEDULED_FETCH_CONFIG = config_data['scheduled_fetch']
        
        logger.info(f"✅ Saved scheduled fetch config to {CONFIG_FILE}: {SCHEDULED_FETCH_CONFIG['hour']:02d}:{SCHEDULED_FETCH_CONFIG['minute']:02d}:{SCHEDULED_FETCH_CONFIG['second']:02d} IST")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving {CONFIG_FILE}: {e}")
        return False

async def update_scheduled_fetch_config(config: Dict):
    """Update scheduled fetch config in config.json file"""
    return await asyncio.to_thread(save_scheduled_fetch_config, config)

async def run_scheduled_fetch_quotes():
    """
    Background task that runs fetch quotes at scheduled time from config.json
    Uses short sleep intervals (60s) for reliability instead of long sleeps.
    Includes heartbeat logging and auto-recovery.
    Reloads config.json on each loop to pick up changes.
    """
    # Load config first
    load_scheduled_fetch_config_sync()
    target_time_str = f"{SCHEDULED_FETCH_CONFIG['hour']:02d}:{SCHEDULED_FETCH_CONFIG['minute']:02d}:{SCHEDULED_FETCH_CONFIG['second']:02d}"
    logger.info(f"📅 Scheduled fetch quotes task started - will run at {target_time_str} IST (Mon-Fri)")
    
    # Calculate and log next run time at startup
    now = get_ist_now()
    next_run = now.replace(
        hour=SCHEDULED_FETCH_CONFIG['hour'],
        minute=SCHEDULED_FETCH_CONFIG['minute'],
        second=SCHEDULED_FETCH_CONFIG['second'],
        microsecond=0
    )
    
    # If time has passed today or it's weekend, calculate next valid run
    if now >= next_run or now.weekday() > 4:
        next_run = next_run + timedelta(days=1)
    
    # Skip to Monday if next_run falls on weekend
    while next_run.weekday() > 4:
        next_run = next_run + timedelta(days=1)
    
    hours_until = (next_run - now).total_seconds() / 3600
    logger.info(f"📅 Next scheduled run: {next_run.strftime('%Y-%m-%d %H:%M:%S')} IST ({next_run.strftime('%A')}) - in {hours_until:.1f} hours")
    
    last_heartbeat = get_ist_now()
    last_run_date = None  # Track which date we last ran to prevent duplicate runs
    
    while True:
        try:
            # Reload config from file every loop to pick up changes
            load_scheduled_fetch_config_sync()
            
            if not SCHEDULED_FETCH_CONFIG["enabled"]:
                await asyncio.sleep(60)
                continue
            
            now = get_ist_now()
            
            # Heartbeat log every 30 minutes to confirm task is alive
            if (now - last_heartbeat).total_seconds() >= 1800:  # 30 minutes
                target_hour = SCHEDULED_FETCH_CONFIG["hour"]
                target_min = SCHEDULED_FETCH_CONFIG["minute"]
                target_sec = SCHEDULED_FETCH_CONFIG["second"]
                logger.info(f"💓 Scheduled task heartbeat - waiting for {target_hour:02d}:{target_min:02d}:{target_sec:02d} IST (current: {now.strftime('%H:%M:%S')} IST, weekday: {now.strftime('%A')})")
                last_heartbeat = now
            
            # Check if weekday (Mon=0, Fri=4)
            is_weekday = now.weekday() <= 4
            
            if SCHEDULED_FETCH_CONFIG["weekdays_only"] and not is_weekday:
                # Weekend - sleep 60 seconds and check again
                await asyncio.sleep(60)
                continue
            
            # Check if it's time to run (within 30 second window)
            target_hour = SCHEDULED_FETCH_CONFIG["hour"]
            target_min = SCHEDULED_FETCH_CONFIG["minute"]
            target_sec = SCHEDULED_FETCH_CONFIG["second"]
            
            current_hour = now.hour
            current_min = now.minute
            current_sec = now.second
            
            # Calculate seconds since midnight for comparison
            target_seconds = target_hour * 3600 + target_min * 60 + target_sec
            current_seconds = current_hour * 3600 + current_min * 60 + current_sec
            
            # Check if we're within the execution window (0-20 seconds after target time)
            time_diff = current_seconds - target_seconds
            today_date = now.date()
            
            should_run = (
                0 <= time_diff <= 20 and  # Within 20 second window after target
                last_run_date != today_date and  # Haven't run today
                is_weekday  # Is a weekday
            )
            
            if should_run:
                logger.info(f"⏰ Scheduled time reached! Running fetch quotes at {now.strftime('%Y-%m-%d %H:%M:%S')} IST")
                scheduled_fetch_logger.info(f"STARTED - {now.strftime('%Y-%m-%d %H:%M:%S')} IST")
                last_run_date = today_date  # Mark as run for today
            
                # Broadcast start notification to frontend
                logger.info("🚀 SCHEDULED FETCH QUOTES STARTING...")
                await ws_manager.broadcast_message({
                    "type": "scheduled_task",
                    "status": "started",
                    "task": "fetch_quotes",
                    "message": "📊 Scheduled fetch quotes started (9:07:10 AM IST)",
                    "timestamp": now.isoformat()
                })
                
                # Check if session is valid before running
                session_file = "kotak_session.json"
                if not os.path.exists(session_file):
                    logger.warning("⚠️ Scheduled fetch skipped - no active session")
                    scheduled_fetch_logger.info(f"SKIPPED - {now.strftime('%Y-%m-%d %H:%M:%S')} IST - No active session")
                    await ws_manager.broadcast_message({
                        "type": "scheduled_task",
                        "status": "skipped",
                        "task": "fetch_quotes",
                        "message": "⚠️ Scheduled fetch skipped - Please verify TOTP first",
                        "timestamp": get_ist_now().isoformat()
                    })
                else:
                    # Run the fetch quotes logic
                    try:
                        from get_quote import (
                            get_gsheet_stocks_df, get_symbol_from_gsheet_stocks_df,
                            flatten_quote_result_list, fetch_ohlc_from_quote_result,
                            update_df_with_quote_ohlc, write_quote_ohlc_to_gsheet,
                            get_quotes_with_rate_limit
                        )
                        from gsheet_stock_get import GSheetStockClient
                        
                        # Broadcast progress
                        await ws_manager.broadcast_message({
                            "type": "scheduled_task",
                            "status": "progress",
                            "task": "fetch_quotes",
                            "progress": 10,
                            "message": "📊 Loading stock data from Google Sheet...",
                            "timestamp": get_ist_now().isoformat()
                        })
                        
                        sheet_url = f"{os.getenv('BASE_SHEET_URL')}{os.getenv('sheet_gid')}"
                        gsheet_client = GSheetStockClient()
                        df = await gsheet_client.get_stock_dataframe(sheet_url)
                        all_rows = await get_gsheet_stocks_df(df)
                        
                        await ws_manager.broadcast_message({
                            "type": "scheduled_task",
                            "status": "progress",
                            "task": "fetch_quotes",
                            "progress": 20,
                            "message": f"📊 Creating symbols for {len(all_rows)} stocks...",
                            "timestamp": get_ist_now().isoformat()
                        })
                        
                        symbols_list, valid_indices = await get_symbol_from_gsheet_stocks_df(all_rows)
                        total_symbols = len(symbols_list)
                        
                        # Fetch quotes with rate limiting (190 req/min)
                        batch_size = 190
                        symbol_batches = [
                            symbols_list[i:i + batch_size]
                            for i in range(0, total_symbols, batch_size)
                        ]
                        all_quote_results = await get_quotes_with_rate_limit(symbol_batches, requests_per_minute=190)
                        
                        # Process results
                        await ws_manager.broadcast_message({
                            "type": "scheduled_task",
                            "status": "progress",
                            "task": "fetch_quotes",
                            "progress": 80,
                            "message": "📊 Processing quote results...",
                            "timestamp": get_ist_now().isoformat()
                        })
                        
                        flattened_quote_result = await flatten_quote_result_list(all_quote_results)
                        quote_ohlc = await fetch_ohlc_from_quote_result(flattened_quote_result)
                        df = await update_df_with_quote_ohlc(df, quote_ohlc, valid_indices)
                        
                        await ws_manager.broadcast_message({
                            "type": "scheduled_task",
                            "status": "progress",
                            "task": "fetch_quotes",
                            "progress": 90,
                            "message": "📊 Writing to Google Sheet...",
                            "timestamp": get_ist_now().isoformat()
                        })
                        
                        await write_quote_ohlc_to_gsheet(df, os.getenv("sheet_id"), os.getenv("sheet_gid"))
                        
                        # Broadcast completion
                        logger.info(f"✅ Scheduled fetch quotes completed - {total_symbols} stocks processed")
                        scheduled_fetch_logger.info(f"COMPLETED - {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')} IST - {total_symbols} stocks processed")
                        await ws_manager.broadcast_message({
                            "type": "scheduled_task",
                            "status": "completed",
                            "task": "fetch_quotes",
                            "progress": 100,
                            "message": f"✅ Scheduled fetch completed - {total_symbols} stocks updated",
                            "timestamp": get_ist_now().isoformat()
                        })
                        
                    except Exception as e:
                        logger.error(f"❌ Scheduled fetch quotes failed: {e}")
                        scheduled_fetch_logger.info(f"FAILED - {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')} IST - {str(e)}")
                        await ws_manager.broadcast_message({
                            "type": "scheduled_task",
                            "status": "failed",
                            "task": "fetch_quotes",
                            "message": f"❌ Scheduled fetch failed: {str(e)}",
                            "timestamp": get_ist_now().isoformat()
                        })
            
            # Always sleep 10 seconds before checking again (frequent checks to catch exact time)
            await asyncio.sleep(10)
            
        except Exception as e:
            logger.error(f"Error in scheduled fetch quotes task: {e}")
            logger.info("🔄 Scheduled task recovering in 10 seconds...")
            await asyncio.sleep(10)

csv_file_path = "files/all_corporate_announcements.csv"
bse_csv_file_path = "files/bse_all_corporate_announcements.csv"
bse_download_folder = Path(__file__).parent / "files" / "bse_downloads"
BSE_PDF_BASE_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive"
watchlist_CA_files = "files/watchlist_corporate_announcements.csv"
# chat_id = "@test_kishore_ai_chat"
TELEGRAM_BOT_TOKEN = "7468886861:AAGA_IllxDqMn06N13D2RNNo8sx9G5qJ0Rc"

# "fundraisensebse"




# Keyword _custom group
gid = "1091746650"
keyword_custom_group_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

# Sector map: all-bse-companies-sectors.xlsx only (BSE Code, NSE Code, Sector)
SECTOR_XLSX_PATH = Path(__file__).parent / "all-bse-companies-sectors.xlsx"
SECTOR_XLSX_PATH_ALT = Path(__file__).parent.parent / "all-bse-companies-sectors.xlsx"
bse_sector_map = {}  # BSE Code (str) -> Sector
nse_sector_map = {}  # NSE Code (str, upper) -> Sector
sector_map = {}  # NSE symbol -> Sector


def load_sector_map():
    """Load sector maps from all-bse-companies-sectors.xlsx. BSE Code, NSE Code -> Sector."""
    global bse_sector_map, nse_sector_map, sector_map
    xlsx_path = SECTOR_XLSX_PATH if SECTOR_XLSX_PATH.exists() else SECTOR_XLSX_PATH_ALT
    bse_sector_map = {}
    nse_sector_map = {}
    sector_map = {}
    try:
        if not xlsx_path.exists():
            logger.warning(f"all-bse-companies-sectors.xlsx not found at {SECTOR_XLSX_PATH} or {SECTOR_XLSX_PATH_ALT}")
            return
        df = pd.read_excel(xlsx_path)
        cols = {str(c).strip().lower(): c for c in df.columns}
        bse_col = cols.get("bse code")
        nse_col = cols.get("nse code")
        sector_col = cols.get("sector")
        if bse_col is None or sector_col is None:
            logger.warning(f"all-bse-companies-sectors.xlsx must have 'BSE Code' and 'Sector'. Found: {list(df.columns)}")
            return
        for _, row in df.iterrows():
            sec = str(row[sector_col]).strip() if pd.notna(row[sector_col]) else ""
            if not sec:
                continue
            bse_code = row.get(bse_col)
            if pd.notna(bse_code) and str(bse_code).strip():
                try:
                    bse_sector_map[str(int(float(bse_code)))] = sec
                except (ValueError, TypeError):
                    pass
            if nse_col and pd.notna(row.get(nse_col)) and str(row[nse_col]).strip():
                nse_sector_map[str(row[nse_col]).strip().upper()] = sec
        sector_map = nse_sector_map
        logger.info(f"Loaded sector map from {xlsx_path.name}: {len(bse_sector_map)} BSE, {len(nse_sector_map)} NSE")
    except Exception as e:
        logger.error(f"Error loading sector map from all-bse-companies-sectors.xlsx: {e}")


def get_sector_for_symbol(symbol: str, exchange: str = "NSE") -> str:
    """Return sector for symbol. BSE: use SCRIP_CD (security number). NSE: use stock symbol."""
    if not symbol:
        return ""
    key = str(symbol).strip()
    if exchange == "BSE":
        key = key.split(".")[0]  # handle 500339.0
        try:
            key = str(int(float(key)))
        except (ValueError, TypeError):
            pass
        return bse_sector_map.get(key, "") if bse_sector_map else ""
    key_upper = key.upper()
    return nse_sector_map.get(key_upper, "") or sector_map.get(key_upper, "") if (nse_sector_map or sector_map) else ""

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


async def save_announcement_to_dashboard(symbol, company_name, description, file_url, exchange="NSE", option="all", message=""):
    """Save every new announcement to dashboard DB and broadcast via WebSocket."""
    try:
        sector = get_sector_for_symbol(symbol, exchange or "NSE") if symbol else ""
        message_data = MessageData(
            chat_id="@dashboard",
            message=message or f"<b>{symbol} - {company_name}</b>\n\n{description}\n\nFile:\n{file_url}",
            timestamp=get_ist_now().isoformat(),
            symbol=symbol,
            company_name=company_name,
            description=description,
            file_url=file_url,
            option=option,
            sector=sector,
            exchange=exchange or "NSE"
        )
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                INSERT INTO messages 
                (chat_id, message, timestamp, symbol, company_name, description, file_url, raw_message, option, sector, exchange)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_data.chat_id,
                message_data.message,
                message_data.timestamp,
                message_data.symbol,
                message_data.company_name,
                message_data.description,
                message_data.file_url,
                message_data.message,
                message_data.option,
                message_data.sector or "",
                message_data.exchange or "NSE"
            ))
            message_id = cursor.lastrowid
            await db.commit()
        await ws_manager.broadcast_message({
            "type": "new_message",
            "message": message_data.dict()
        })
        logger.info(f"Saved to dashboard: {symbol} - {company_name}")
        return message_id
    except Exception as e:
        logger.warning(f"Error saving to dashboard: {e}")
        return None


# this is the test message to see if the script is working or not
# This will send all the CA docs to the trade_mvd chat id ( which is our Script CA running telegram )
async def trigger_test_message(chat_idd, message, type="test", symbol="", company_name="", description="", file_url="", exchange="NSE", save_to_dashboard=True):
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
        sector = get_sector_for_symbol(symbol, exchange or "NSE") if symbol else ""
        # Create message data with all provided fields
        message_data = MessageData(
            chat_id=chat_idd,
            message=message,
            timestamp=get_ist_now().isoformat(),
            symbol=symbol,
            company_name=company_name,
            description=description,
            file_url=file_url,
            option=type,
            sector=sector,
            exchange=exchange or "NSE"
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
        
        # Skip database save and WebSocket for test messages or when save_to_dashboard=False
        if type == "test":
            print(f"✅ Test message sent to Telegram only (not saved to DB): {message_data.symbol} - {message_data.company_name}")
            return None
        if not save_to_dashboard:
            return None

        # Save to database (only non-test messages with save_to_dashboard=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                INSERT INTO messages 
                (chat_id, message, timestamp, symbol, company_name, description, file_url, raw_message, option, sector, exchange)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_data.chat_id,
                message_data.message,
                message_data.timestamp,
                message_data.symbol,
                message_data.company_name,
                message_data.description,
                message_data.file_url,
                message_data.message,
                message_data.option,
                message_data.sector or "",
                message_data.exchange or "NSE"
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

def _parse_period_date(column_header: str) -> datetime:
    """Parse column_header like '30.06.2025' to datetime for sorting."""
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(column_header).strip(), fmt)
        except (ValueError, TypeError):
            continue
    return datetime.min


def _calculate_full_year_eps(periods: List[Dict[str, Any]], eps_key: str = "eps_basic") -> Dict[str, Any]:
    """
    Calculate full_year_estimated_EPS from extracted periods.
    Prefers cumulative period entries (nine_month/six_month) when available, falls back to sum of quarters.
    Q1 -> Q1*4 | Q2 -> N6*2 or (Q1+Q2)*2 | Q3 -> N9*4/3 or (Q1+Q2+Q3)*4/3 | Q4/FY -> annual EPS
    """
    if not periods:
        return {}

    quarterly = [p for p in periods if p.get("period_type") == "quarter"]
    annual = [p for p in periods if p.get("period_type") == "annual"]
    nine_month = [p for p in periods if p.get("period_type") == "nine_month"]
    six_month = [p for p in periods if p.get("period_type") == "six_month"]

    if not quarterly and not annual:
        return {}

    quarterly.sort(key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True)

    latest = quarterly[0] if quarterly else None
    current_q = latest.get("quarter", "").upper() if latest else None
    current_fy = latest.get("financial_year", "") if latest else None

    cum_eps = None
    if current_q == "Q3" and nine_month:
        nm = [p for p in nine_month if p.get("financial_year") == current_fy]
        nm.sort(key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True)
        if nm:
            cum_eps = nm[0].get(eps_key)
    elif current_q == "Q2" and six_month:
        sm = [p for p in six_month if p.get("financial_year") == current_fy]
        sm.sort(key=lambda p: _parse_period_date(p.get("column_header", "")), reverse=True)
        if sm:
            cum_eps = sm[0].get(eps_key)

    same_fy = {}
    for p in quarterly:
        if p.get("financial_year") == current_fy:
            q = p.get("quarter", "").upper()
            eps = p.get(eps_key)
            if eps is not None and q:
                same_fy[q] = eps

    fy_eps = None
    for a in annual:
        if a.get("financial_year") == current_fy:
            fy_eps = a.get(eps_key)
            break

    result = {"current_quarter": current_q, "financial_year": current_fy, "formula": None, "value": None}

    if current_q == "Q4" or (not current_q and fy_eps is not None):
        result["formula"] = "FY"
        result["value"] = fy_eps
    elif current_q == "Q1":
        q1 = same_fy.get("Q1")
        if q1 is not None:
            result["formula"] = "Q1*4"
            result["value"] = round(q1 * 4, 4)
    elif current_q == "Q2":
        if cum_eps is not None:
            result["formula"] = "N6*2"
            result["value"] = round(cum_eps * 2, 4)
        else:
            q1, q2 = same_fy.get("Q1"), same_fy.get("Q2")
            if q1 is not None and q2 is not None:
                result["formula"] = "(Q1+Q2)*2"
                result["value"] = round((q1 + q2) * 2, 4)
            elif q2 is not None:
                result["formula"] = "Q2*4"
                result["value"] = round(q2 * 4, 4)
    elif current_q == "Q3":
        if cum_eps is not None:
            result["formula"] = "N9*4/3"
            result["value"] = round(cum_eps * 4 / 3, 4)
        else:
            vals = [same_fy.get(q) for q in ("Q1", "Q2", "Q3")]
            available = [v for v in vals if v is not None]
            if available:
                n = len(available)
                result["formula"] = f"sum({n}Q)*4/{n}"
                result["value"] = round(sum(available) * 4 / n, 4)
    elif current_q == "FY":
        result["formula"] = "FY"
        result["value"] = fy_eps

    return result


def _compute_all_fy_eps(ai_response: Dict[str, Any]) -> Dict[str, Any]:
    """Compute full_year_estimated_eps for all 4 combinations (standalone/consolidated × basic/diluted)."""
    standalone = ai_response.get("standalone_periods", [])
    consolidated = ai_response.get("consolidated_periods", [])

    return {
        "fy_eps_basic_standalone": _calculate_full_year_eps(standalone, "eps_basic"),
        "fy_eps_diluted_standalone": _calculate_full_year_eps(standalone, "eps_diluted"),
        "fy_eps_basic_consolidated": _calculate_full_year_eps(consolidated, "eps_basic"),
        "fy_eps_diluted_consolidated": _calculate_full_year_eps(consolidated, "eps_diluted"),
    }


async def _upsert_quarterly_result(db, stock_symbol, company_name, quarter, financial_year,
                                    period_ended, standalone_data, consolidated_data,
                                    raw_ai_response, source_pdf_url, source_message_id,
                                    exchange, units, now_iso, stock_id=None,
                                    fy_eps_basic_s=None, fy_eps_diluted_s=None,
                                    fy_eps_basic_c=None, fy_eps_diluted_c=None,
                                    fy_eps_formula_s=None, fy_eps_formula_c=None):
    """UPSERT a single quarterly result row with full-year estimated EPS and stock_id FK."""
    eps_basic_s = standalone_data.get('eps_basic') if standalone_data else None
    eps_diluted_s = standalone_data.get('eps_diluted') if standalone_data else None
    eps_basic_c = consolidated_data.get('eps_basic') if consolidated_data else None
    eps_diluted_c = consolidated_data.get('eps_diluted') if consolidated_data else None
    cum_eps_basic_s = standalone_data.get('cumulative_eps_basic') if standalone_data else None
    cum_eps_diluted_s = standalone_data.get('cumulative_eps_diluted') if standalone_data else None
    cum_eps_basic_c = consolidated_data.get('cumulative_eps_basic') if consolidated_data else None
    cum_eps_diluted_c = consolidated_data.get('cumulative_eps_diluted') if consolidated_data else None

    await db.execute("""
        INSERT INTO quarterly_results
        (stock_symbol, company_name, quarter, financial_year, period_ended,
         eps_basic_standalone, eps_diluted_standalone, eps_basic_consolidated, eps_diluted_consolidated,
         fy_eps_basic_standalone, fy_eps_diluted_standalone,
         fy_eps_basic_consolidated, fy_eps_diluted_consolidated,
         fy_eps_formula_standalone, fy_eps_formula_consolidated,
         cumulative_eps_basic_standalone, cumulative_eps_diluted_standalone,
         cumulative_eps_basic_consolidated, cumulative_eps_diluted_consolidated,
         standalone_data, consolidated_data, raw_ai_response,
         source_pdf_url, source_message_id, exchange, units, stock_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_symbol, quarter, financial_year)
        DO UPDATE SET
            company_name = excluded.company_name,
            period_ended = excluded.period_ended,
            eps_basic_standalone = excluded.eps_basic_standalone,
            eps_diluted_standalone = excluded.eps_diluted_standalone,
            eps_basic_consolidated = excluded.eps_basic_consolidated,
            eps_diluted_consolidated = excluded.eps_diluted_consolidated,
            fy_eps_basic_standalone = excluded.fy_eps_basic_standalone,
            fy_eps_diluted_standalone = excluded.fy_eps_diluted_standalone,
            fy_eps_basic_consolidated = excluded.fy_eps_basic_consolidated,
            fy_eps_diluted_consolidated = excluded.fy_eps_diluted_consolidated,
            fy_eps_formula_standalone = excluded.fy_eps_formula_standalone,
            fy_eps_formula_consolidated = excluded.fy_eps_formula_consolidated,
            cumulative_eps_basic_standalone = excluded.cumulative_eps_basic_standalone,
            cumulative_eps_diluted_standalone = excluded.cumulative_eps_diluted_standalone,
            cumulative_eps_basic_consolidated = excluded.cumulative_eps_basic_consolidated,
            cumulative_eps_diluted_consolidated = excluded.cumulative_eps_diluted_consolidated,
            standalone_data = excluded.standalone_data,
            consolidated_data = excluded.consolidated_data,
            raw_ai_response = excluded.raw_ai_response,
            source_pdf_url = excluded.source_pdf_url,
            units = excluded.units,
            stock_id = excluded.stock_id,
            updated_at = excluded.updated_at
    """, (
        stock_symbol, company_name, quarter, financial_year, period_ended,
        eps_basic_s, eps_diluted_s, eps_basic_c, eps_diluted_c,
        fy_eps_basic_s, fy_eps_diluted_s, fy_eps_basic_c, fy_eps_diluted_c,
        fy_eps_formula_s, fy_eps_formula_c,
        cum_eps_basic_s, cum_eps_diluted_s, cum_eps_basic_c, cum_eps_diluted_c,
        json.dumps(standalone_data) if standalone_data else None,
        json.dumps(consolidated_data) if consolidated_data else None,
        json.dumps(raw_ai_response) if raw_ai_response else None,
        source_pdf_url, source_message_id, exchange, units, stock_id,
        now_iso, now_iso
    ))


async def process_quarterly_results(ai_response, stock_symbol, message_id=None, pdf_url=None, exchange=None):
    """Process AI quarterly results (flat array structure) and UPSERT into quarterly_results table."""
    try:
        if not ai_response or ai_response.get('error'):
            logger.warning(f"No valid quarterly results for {stock_symbol}: {ai_response.get('error', 'empty')}")
            return []

        company_name = ai_response.get('company_name')
        units = ai_response.get('units')
        standalone_periods = ai_response.get('standalone_periods', [])
        consolidated_periods = ai_response.get('consolidated_periods', [])

        if not standalone_periods and not consolidated_periods:
            logger.warning(f"No periods extracted for {stock_symbol}")
            return []

        fy_eps = _compute_all_fy_eps(ai_response)
        fy_basic_s = fy_eps["fy_eps_basic_standalone"].get("value")
        fy_diluted_s = fy_eps["fy_eps_diluted_standalone"].get("value")
        fy_basic_c = fy_eps["fy_eps_basic_consolidated"].get("value")
        fy_diluted_c = fy_eps["fy_eps_diluted_consolidated"].get("value")
        fy_formula_s = fy_eps["fy_eps_basic_standalone"].get("formula")
        fy_formula_c = fy_eps["fy_eps_basic_consolidated"].get("formula")

        logger.info(f"FY EPS for {stock_symbol}: S_basic={fy_basic_s} ({fy_formula_s}), C_basic={fy_basic_c} ({fy_formula_c})")

        # Build a lookup: (quarter, financial_year) → {standalone_data, consolidated_data}
        # Separate cumulative entries (six_month/nine_month) from quarterly/annual
        period_map = {}
        cum_map_s = {}  # (quarter, fy) → cumulative standalone data
        cum_map_c = {}  # (quarter, fy) → cumulative consolidated data
        for p in standalone_periods:
            q = p.get('quarter')
            fy = p.get('financial_year')
            pt = p.get('period_type', 'quarter')
            if not q or not fy:
                continue
            data = {k: v for k, v in p.items() if k not in ('column_header', 'period_type', 'quarter', 'financial_year')}
            if pt in ('six_month', 'nine_month'):
                cum_map_s[(q, fy)] = data
            else:
                key = (q, fy)
                if key not in period_map:
                    period_map[key] = {"period_ended": p.get('column_header'), "standalone": None, "consolidated": None}
                period_map[key]["standalone"] = data

        for p in consolidated_periods:
            q = p.get('quarter')
            fy = p.get('financial_year')
            pt = p.get('period_type', 'quarter')
            if not q or not fy:
                continue
            data = {k: v for k, v in p.items() if k not in ('column_header', 'period_type', 'quarter', 'financial_year')}
            if pt in ('six_month', 'nine_month'):
                cum_map_c[(q, fy)] = data
            else:
                key = (q, fy)
                if key not in period_map:
                    period_map[key] = {"period_ended": p.get('column_header'), "standalone": None, "consolidated": None}
                period_map[key]["consolidated"] = data

        # Inject cumulative EPS into matching quarterly entries
        for (q, fy), cum_data in cum_map_s.items():
            if (q, fy) in period_map and period_map[(q, fy)]["standalone"]:
                period_map[(q, fy)]["standalone"]["cumulative_eps_basic"] = cum_data.get("eps_basic")
                period_map[(q, fy)]["standalone"]["cumulative_eps_diluted"] = cum_data.get("eps_diluted")
        for (q, fy), cum_data in cum_map_c.items():
            if (q, fy) in period_map and period_map[(q, fy)]["consolidated"]:
                period_map[(q, fy)]["consolidated"]["cumulative_eps_basic"] = cum_data.get("eps_basic")
                period_map[(q, fy)]["consolidated"]["cumulative_eps_diluted"] = cum_data.get("eps_diluted")

        now_iso = get_ist_now().isoformat()
        stored = []

        async with aiosqlite.connect(DB_PATH) as db:
            stock_id = await get_or_create_stock(db, stock_symbol, company_name, exchange)
            for (quarter, fy), data in period_map.items():
                await _upsert_quarterly_result(
                    db, stock_symbol, company_name, quarter, fy,
                    data["period_ended"], data["standalone"], data["consolidated"],
                    ai_response if not stored else None,
                    pdf_url, message_id, exchange, units, now_iso,
                    stock_id=stock_id,
                    fy_eps_basic_s=fy_basic_s, fy_eps_diluted_s=fy_diluted_s,
                    fy_eps_basic_c=fy_basic_c, fy_eps_diluted_c=fy_diluted_c,
                    fy_eps_formula_s=fy_formula_s, fy_eps_formula_c=fy_formula_c,
                )
                stored.append({"stock_symbol": stock_symbol, "quarter": quarter, "financial_year": fy})
            await db.commit()

        logger.info(f"Stored {len(stored)} quarterly results for {stock_symbol}")

        # Auto-fetch CMP + compute PE (best EPS: consolidated diluted > basic > standalone)
        best_fy_eps = fy_diluted_c or fy_basic_c or fy_diluted_s or fy_basic_s
        cmp_result = {"cmp": None, "pe": None, "error": None}
        if best_fy_eps and best_fy_eps > 0:
            cmp_result = await _auto_fetch_cmp_for_stock(stock_symbol, best_fy_eps, exchange=exchange)

        await ws_manager.broadcast_message({
            "type": "quarterly_results",
            "data": {
                "stock_symbol": stock_symbol,
                "results": stored,
                "total": len(stored),
                "cmp": cmp_result.get("cmp"),
                "pe": cmp_result.get("pe"),
                "cmp_hint": cmp_result.get("error"),
            }
        })

        return {"stored": stored, "cmp_result": cmp_result}

    except Exception as e:
        logger.error(f"Error processing quarterly results for {stock_symbol}: {e}")
        return {"stored": [], "cmp_result": {"error": str(e)}}


_FINANCIAL_KEYWORDS = ['revenue', 'expense', 'tax', 'profit', 'earning',
                       'income', 'eps', 'share capital', 'diluted', 'comprehensive']
_MIN_KEYWORD_MATCHES = 3


def _extract_text_pymupdf(pdf_path: str) -> list:
    """Extract text from each page using PyMuPDF (no OCR, no Poppler)."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        pages.append({"page_num": i + 1, "text": text, "has_text": bool(text.strip())})
    doc.close()
    return pages


def _find_financial_pages(pages: list) -> list:
    """Filter pages that contain financial keywords."""
    financial = []
    for p in pages:
        text_lower = p["text"].lower()
        matches = sum(1 for kw in _FINANCIAL_KEYWORDS if kw in text_lower)
        if matches >= _MIN_KEYWORD_MATCHES:
            financial.append(p["page_num"])
    return financial


def _find_financial_pages_image_fallback(total_pages: int) -> list:
    """For image-based PDFs where text extraction fails: send first N pages to AI."""
    return list(range(1, min(total_pages + 1, 7)))


def _render_page_to_png_bytes(pdf_path: str, page_num: int, dpi: int = 150) -> bytes:
    """Render a single page to PNG bytes using PyMuPDF."""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


async def _extract_financial_pages_as_b64(pdf_path: str) -> list:
    """PyMuPDF pipeline: text extract → keyword filter → render financial pages → base64."""
    pages = await asyncio.to_thread(_extract_text_pymupdf, pdf_path)
    total_pages = len(pages)
    text_pages = sum(1 for p in pages if p["has_text"])
    logger.info(f"PyMuPDF: {total_pages} pages, {text_pages} with text")

    if text_pages > 0:
        financial_page_nums = _find_financial_pages(pages)
        if not financial_page_nums and text_pages < total_pages:
            logger.info("Text extraction found no financial pages, trying image fallback")
            financial_page_nums = _find_financial_pages_image_fallback(total_pages)
    else:
        logger.info("No text layer found — image-based PDF, using fallback")
        financial_page_nums = _find_financial_pages_image_fallback(total_pages)

    if not financial_page_nums:
        logger.warning("No financial pages detected in PDF")
        return []

    logger.info(f"PyMuPDF: rendering {len(financial_page_nums)} financial pages: {financial_page_nums}")
    encoded_images = []
    for pn in financial_page_nums:
        png_bytes = await asyncio.to_thread(_render_page_to_png_bytes, pdf_path, pn)
        encoded_images.append(base64.b64encode(png_bytes).decode("utf-8"))

    return encoded_images


async def _call_openai_vision_quarterly(encoded_images: list) -> dict:
    """Single OpenAI Vision call with all financial page images for quarterly extraction."""
    client = AsyncOpenAI()

    base_prompt = """You are extracting data from an Indian company's quarterly financial results PDF.

The document may have TWO tables: Standalone and Consolidated (check the title of each table).

**TABLE STRUCTURE:**
Each table typically has 4-6+ data columns:
- 3 columns under "Quarter ended" header (individual quarterly periods)
- 0-2 columns under "Six Month ended" / "Nine Month ended" header (cumulative periods — NOT always present)
- 1 column under "Year Ended" header (full year annual data)
You MUST extract ALL columns as separate entries — quarterly, cumulative, AND annual.

**ROW STRUCTURE (top to bottom in each table):**
Row 1: "Revenue from Operations" — this is the FIRST income row
Row 2: "Other Income" — this is the SECOND income row (separate from Revenue)
Row 3: "Total Income" — sum row
Then expense rows, then profit rows, then tax, then EPS at bottom.

**CRITICAL — DASH HANDLING:**
- A dash (-) means null. Return null, not 0, not 0.0.

**face_value:** Read from the row label text "Face Value Rs. X/- Each".

**Quarter & Financial Year mapping (Indian FY):**
- June ending → Q1, FY = next March's year
- September ending → Q2, FY = next March's year
- December ending → Q3, FY = next March's year
- March ending → Q4, FY = same year
- Year Ended column → period_type = "annual", quarter = "FY"

**period_type mapping for cumulative columns:**
- "Six Month ended" column → period_type = "six_month", quarter = same as matching quarterly date (Q2)
- "Nine Month ended" column → period_type = "nine_month", quarter = same as matching quarterly date (Q3)
- These are FULL entries with ALL rows extracted (revenue, expenses, PAT, EPS, etc.), same schema as quarterly entries.

IMPORTANT: Return ONLY raw JSON. No markdown, no code blocks.
If a page is NOT a financial results table, IGNORE it completely.

{
    "company_name": "string",
    "units": "lakhs or crores",
    "standalone_periods": [
        {
            "column_header": "30.06.2025",
            "period_type": "quarter | six_month | nine_month | annual",
            "quarter": "Q1",
            "financial_year": "2026",
            "revenue_from_operations": number_or_null,
            "other_income": number_or_null,
            "total_income": number_or_null,
            "total_expenses": number_or_null,
            "profit_before_exceptional": number_or_null,
            "exceptional_items": number_or_null,
            "profit_before_tax": number_or_null,
            "tax_expense": number_or_null,
            "profit_after_tax": number_or_null,
            "profit_attributable_to_minority": number_or_null,
            "other_comprehensive_income": number_or_null,
            "total_comprehensive_income": number_or_null,
            "paid_up_equity_share_capital": number_or_null,
            "face_value": number_or_null,
            "eps_basic": number_or_null,
            "eps_diluted": number_or_null
        }
    ],
    "consolidated_periods": []
}

Rules:
- Extract EVERY data column as a separate entry: quarterly columns + cumulative columns (six_month/nine_month) + annual column.
- A Q3 PDF typically has: 3 quarterly + 2 nine_month + 1 annual = 6 entries per table.
- A Q2 PDF typically has: 3 quarterly + 2 six_month + 1 annual = 6 entries per table.
- null for dash (-) or blank cells. Never use 0 or 0.0 for dashes.
- Return numbers exactly as printed in the document."""

    content = [{"type": "text", "text": base_prompt}]
    for img_b64 in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })
    content.append({
        "type": "text",
        "text": "\nSTEP-BY-STEP EXTRACTION:\n"
               "1. Each image = one table (Standalone or Consolidated). Identify which from the title.\n"
               "2. Locate ALL data columns: quarterly + cumulative (Six/Nine Month ended) + annual (Year Ended).\n"
               "3. For EACH column (including cumulative), extract ALL rows as a full entry with the correct period_type.\n"
               "4. Cumulative columns get period_type 'six_month' or 'nine_month', with quarter matching the date.\n"
               "5. Do NOT skip any column. Do NOT skip the Year Ended column.\n"
               "6. VERIFY per column: Total Income ≈ Revenue + Other Income."
    })

    t0 = time.time()
    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": content}],
        temperature=0,
        max_tokens=16000,
        response_format={"type": "json_object"}
    )
    elapsed = time.time() - t0
    usage = response.usage
    logger.info(f"OpenAI quarterly vision: {elapsed:.1f}s | tokens: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}")

    return json.loads(response.choices[0].message.content)


async def _call_openai_vision_general(encoded_images: list) -> dict:
    """Single OpenAI Vision call for general financial metrics extraction."""
    client = AsyncOpenAI()

    base_prompt = """Extract these financial metrics from the provided images and return as JSON:

    Extract:
    1. revenue_from_operations
    2. profit_after_tax
    3. profit_before_tax
    4. total_income
    5. other_income
    6. earnings_per_share

    Also get the quarterly values with period and year ended in a list of JSON.

    IMPORTANT: Return only the raw JSON object without any markdown formatting, code blocks, or additional text.

    Return JSON format:
    {
        "revenue_from_operations": number_or_null,
        "profit_after_tax": number_or_null,
        "profit_before_tax": number_or_null,
        "total_income": number_or_null,
        "other_income": number_or_null,
        "earnings_per_share": number_or_null,
        "units": "crores_or_lakhs_or_null",
        "quarterly_data": [
            {
                "period": "Q1/Q2/Q3/Q4",
                "year_ended": "YYYY",
                "revenue_from_operations": number_or_null,
                "profit_after_tax": number_or_null,
                "profit_before_tax": number_or_null,
                "total_income": number_or_null,
                "other_income": number_or_null,
                "earnings_per_share": number_or_null
            }
        ]
    }"""

    content = [{"type": "text", "text": base_prompt}]
    for img_b64 in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })

    t0 = time.time()
    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": content}],
        temperature=0,
        response_format={"type": "json_object"}
    )
    elapsed = time.time() - t0
    usage = response.usage
    logger.info(f"OpenAI general vision: {elapsed:.1f}s | tokens: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}")

    result = json.loads(response.choices[0].message.content)
    result["analysis_metadata"] = {
        "images_provided": len(encoded_images),
        "total_content_items": len(content)
    }
    return result


async def run_quarterly_extraction(pdf_url, stock_symbol, message_id=None, exchange=None):
    """Full pipeline: PDF download → PyMuPDF extract → AI quarterly extraction → DB store."""
    try:
        pdf_path = await download_pdf_async(pdf_url, "downloads_concall")

        encoded_images = await _extract_financial_pages_as_b64(pdf_path)
        if not encoded_images:
            logger.error(f"No financial pages found in PDF for {stock_symbol}")
            return None

        ai_response = await _call_openai_vision_quarterly(encoded_images)
        result = await process_quarterly_results(ai_response, stock_symbol, message_id, pdf_url, exchange)
        return result

    except Exception as e:
        logger.error(f"Quarterly extraction failed for {stock_symbol}: {e}")
        return None


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
                
                # Convert all row values to lowercase strings for keyword matching
                row_values = [str(val).lower() for val in row]
                
                # Determine option for dashboard: first matched or "all"
                dashboard_option = "all"
                for group_id, data in group_id_keywords.items():
                    keywords = data.get('keywords', [])
                    option = data.get('option', '')
                    keywords_lower = [str(kw).lower() for kw in keywords]
                    if any(any(kw in val for val in row_values) for kw in keywords_lower):
                        dashboard_option = option
                        break
                
                # Save every announcement to dashboard (DB + WebSocket)
                message_id = await save_announcement_to_dashboard(
                    row['symbol'], row['sm_name'], row['desc'], attachment_file,
                    exchange="NSE", option=dashboard_option, message=message
                )
                
                # Send to trade_mvd (Telegram only, not saved to DB)
                await trigger_test_message("@trade_mvd", message, "test", row['symbol'], row['sm_name'], row['desc'], attachment_file, exchange="NSE")
                
                
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
                    
                ###############################################################
                ###### x --------- sending watchlist message -------x ########
                for group_id, data in group_id_keywords.items():
                    keywords = data.get('keywords', [])
                    option = data.get('option', '')
                    keywords_lower = [str(kw).lower() for kw in keywords]
                    if any(any(kw in val for val in row_values) for kw in keywords_lower):
                        await trigger_test_message(group_id, message, option, row['symbol'], row['sm_name'], row['desc'], attachment_file, exchange="NSE", save_to_dashboard=False)
                ###### X --------------------------------------------X #########      
                ################################################################
                
                
                
                ################################################################
                ###### x ---- Quarterly extraction (quarterly_results only) ---- x ########
                if dashboard_option in ("quaterly_result", "quarterly_result"):
                    asyncio.create_task(
                        run_quarterly_extraction(attachment_file, row['symbol'], message_id, exchange="NSE")
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

def _fetch_bse_announcements_sync():
    """Sync BSE fetch - run in executor. Returns raw BSE API response."""
    bse_download_folder.mkdir(parents=True, exist_ok=True)
    with BSE(bse_download_folder) as bse:
        return bse.announcements(page_no=1, segment="equity")


async def fetch_bse_announcements():
    """Fetch BSE corporate announcements (runs sync BSE in executor)."""
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_bse_announcements_sync)
    except Exception as e:
        logger.error(f"BSE fetch failed: {e}")
        return None


def _bse_row_to_normalized(row: dict) -> dict:
    """Map BSE API row to NSE-like normalized format for dashboard/processing."""
    att_name = row.get("ATTACHMENTNAME") or ""
    att_url = f"{BSE_PDF_BASE_URL}/{att_name.strip()}" if att_name and str(att_name).strip() else "-"
    return {
        "symbol": str(row.get("SCRIP_CD", "")),
        "sm_name": str(row.get("SLONGNAME", "")),
        "desc": str(row.get("HEADLINE") or row.get("NEWSSUB", "")),
        "attchmntFile": att_url,
        "an_dt": str(row.get("DT_TM", "")),
        "NEWSID": str(row.get("NEWSID", "")),
    }


async def process_bse_ca_data(bse_data):
    """Process BSE corporate announcements - separate CSV, normalized for dashboard."""
    if not bse_data or "Table" not in bse_data:
        logger.warning("BSE data empty or invalid structure")
        return None
    table = bse_data["Table"]
    if not table:
        return 1
    existing_newsids = set()
    if await aiofiles.os.path.exists(bse_csv_file_path):
        async with aiofiles.open(bse_csv_file_path, mode="r") as f:
            content = await f.read()
            df_existing = pd.read_csv(io.StringIO(content), dtype="object")
            if "NEWSID" in df_existing.columns:
                existing_newsids = set(df_existing["NEWSID"].dropna().astype(str).str.strip())
    normalized_rows = []
    raw_rows_to_append = []
    for row in table:
        newsid = str(row.get("NEWSID", "")).strip()
        if newsid in existing_newsids:
            continue
        norm = _bse_row_to_normalized(row)
        normalized_rows.append(norm)
        raw_rows_to_append.append(row)
    if not normalized_rows:
        return 1
    try:
        group_id_keywords = await load_group_keywords_async()
    except Exception as e:
        logger.error(f"Error loading group keywords: {e}")
        group_id_keywords = {}
    for norm_row in normalized_rows:
        attachment_file = norm_row["attchmntFile"]
        message = f'''<b>{norm_row['symbol']} - {norm_row['sm_name']}</b>\n\n{norm_row['desc']}\n\nFile:\n <a href="{attachment_file}">{attachment_file}</a>'''
        row_values = [str(v).lower() for v in norm_row.values()]
        
        # Determine option for dashboard
        dashboard_option = "all"
        for group_id, data in group_id_keywords.items():
            keywords = data.get("keywords", [])
            option = data.get("option", "")
            keywords_lower = [str(kw).lower() for kw in keywords]
            if any(any(kw in val for val in row_values) for kw in keywords_lower):
                dashboard_option = option
                break
        
        # Save every announcement to dashboard
        message_id = await save_announcement_to_dashboard(
            norm_row["symbol"], norm_row["sm_name"], norm_row["desc"], attachment_file,
            exchange="BSE", option=dashboard_option, message=message
        )
        
        await trigger_test_message(
            "@trade_mvd", message, "test",
            norm_row["symbol"], norm_row["sm_name"], norm_row["desc"],
            attachment_file, exchange="BSE"
        )
        for group_id, data in group_id_keywords.items():
            keywords = data.get("keywords", [])
            option = data.get("option", "")
            keywords_lower = [str(kw).lower() for kw in keywords]
            if any(any(kw in val for val in row_values) for kw in keywords_lower):
                await trigger_test_message(
                    group_id, message, option,
                    norm_row["symbol"], norm_row["sm_name"], norm_row["desc"],
                    attachment_file, exchange="BSE", save_to_dashboard=False
                )
        # Quarterly extraction (quarterly_results only)
        if dashboard_option in ("quaterly_result", "quarterly_result"):
            asyncio.create_task(
                run_quarterly_extraction(attachment_file, norm_row["symbol"], message_id, exchange="BSE")
            )
    df_raw = pd.DataFrame(raw_rows_to_append)
    if await aiofiles.os.path.exists(bse_csv_file_path):
        df_existing = pd.read_csv(bse_csv_file_path, dtype="object")
        df_updated = pd.concat([df_raw, df_existing], ignore_index=True)
    else:
        df_updated = df_raw
    Path(bse_csv_file_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(bse_csv_file_path, mode="w") as f:
        await f.write(df_updated.to_csv(index=False))
    logger.info(f"BSE CSV updated with {len(raw_rows_to_append)} new rows")
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


async def CA_bse():
    """Fetch BSE corporate announcements and process. Runs in parallel with NSE."""
    try:
        bse_data = await fetch_bse_announcements()
        if bse_data:
            return await process_bse_ca_data(bse_data)
    except Exception as e:
        logger.error(f"BSE CA error: {e}")
    return None


# Function to run the periodic task
async def run_periodic_task_equities():
    global ai_processing_active
    logger.info("Starting NSE + BSE corporate announcements task")
    while True:
        try:
            if ai_processing_active:
                logger.info("AI processing active, pausing background task...")
                await asyncio.sleep(10)
                continue
            logger.info("Fetching NSE + BSE in parallel...")
            nse_task = asyncio.create_task(CA_equities())
            bse_task = asyncio.create_task(CA_bse())
            nse_result, bse_result = await asyncio.gather(nse_task, bse_task)
            if nse_result is None:
                logger.warning("NSE fetch failed, will retry next cycle")
            else:
                logger.info("NSE fetch completed")
            if bse_result is None:
                logger.warning("BSE fetch failed, will retry next cycle")
            else:
                logger.info("BSE fetch completed")
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Error in run_periodic_task_equities: {str(e)}")
            await asyncio.sleep(30)




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
            expires_time = parse_datetime_ist(expires_at)
            if expires_time and get_ist_now() > expires_time:
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
        await websocket.send_json({"type": "connected"})
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
        
        # Set sector from symbol if not provided
        if message_data.symbol and not message_data.sector:
            message_data.sector = get_sector_for_symbol(message_data.symbol, message_data.exchange or "NSE")
        
        # Skip "test" option completely - no DB, no WebSocket, Telegram only
        if message_data.option == "test":
            logger.info(f"Test message - Telegram only (not saved to DB or dashboard): {message_data.symbol} - {message_data.company_name}")
            return {"success": True, "message": "Test message sent to Telegram only"}
        
        # Save to database (all options except "test")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO messages 
                (chat_id, message, timestamp, symbol, company_name, description, file_url, raw_message, option, sector, exchange)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_data.chat_id,
                message_data.message,
                message_data.timestamp,
                message_data.symbol,
                message_data.company_name,
                message_data.description,
                message_data.file_url,
                message_data.message,
                message_data.option,
                message_data.sector or "",
                message_data.exchange or "NSE"
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

@app.post("/api/reload_sector_map")
async def reload_sector_map_endpoint():
    """Reload sector map from all-bse-companies-sectors.xlsx"""
    await asyncio.to_thread(load_sector_map)
    bse_count = len(bse_sector_map)
    nse_count = len(nse_sector_map)
    return {
        "success": True,
        "message": "Sector map reloaded",
        "bse_count": bse_count,
        "nse_count": nse_count,
        "source": "xlsx" if bse_count or nse_count else "empty"
    }


async def _backfill_sectors_task():
    """One-time background task: update sector for all existing messages from xlsx map."""
    await asyncio.to_thread(load_sector_map)
    if not bse_sector_map and not nse_sector_map:
        logger.warning("Sector backfill skipped: sector map empty")
        return
    updated = 0
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT id, symbol, exchange FROM messages")
            rows = await cursor.fetchall()
        updates = []
        for row in rows:
            msg_id, symbol, exchange = row[0], row[1] or "", row[2] or "NSE"
            if not symbol:
                continue
            sec = get_sector_for_symbol(str(symbol), exchange)
            if sec:
                updates.append((sec, msg_id))
        if updates:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.executemany("UPDATE messages SET sector = ? WHERE id = ?", updates)
                await db.commit()
                updated = len(updates)
        logger.info(f"Sector backfill done: {updated} messages updated")
    except Exception as e:
        logger.error(f"Sector backfill failed: {e}")


@app.post("/api/backfill_sectors")
async def backfill_sectors_endpoint(background_tasks: BackgroundTasks):
    """Trigger one-time sector backfill for existing messages. Runs in background."""
    background_tasks.add_task(_backfill_sectors_task)
    return {"success": True, "message": "Sector backfill started in background"}


@app.get("/api/messages")
async def get_messages(
    page: int = 1, per_page: int = 50,
    search: str = "", option: str = "", exchange: str = "", sector: str = ""
):
    """Get paginated messages with server-side filtering."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            where_clauses = []
            params = []
            if search:
                q = f"%{search}%"
                where_clauses.append("(symbol LIKE ? OR company_name LIKE ? OR description LIKE ? OR sector LIKE ? OR exchange LIKE ?)")
                params.extend([q, q, q, q, q])
            if option:
                if option == "quarterly_result":
                    where_clauses.append("(option = ? OR option = ?)")
                    params.extend(["quarterly_result", "quaterly_result"])
                else:
                    where_clauses.append("option = ?")
                    params.append(option)
            if exchange:
                where_clauses.append("exchange = ?")
                params.append(exchange)
            if sector:
                where_clauses.append("sector = ?")
                params.append(sector)

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            count_cursor = await db.execute(f"SELECT COUNT(*) FROM messages{where_sql}", params)
            total_filtered = (await count_cursor.fetchone())[0]

            total_pages = max(1, -(-total_filtered // per_page))
            page = max(1, min(page, total_pages))
            offset = (page - 1) * per_page

            cursor = await db.execute(
                f"SELECT * FROM messages{where_sql} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                params + [per_page, offset]
            )
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            messages = [dict(zip(columns, row)) for row in rows]

            return {
                "success": True, "messages": messages,
                "page": page, "per_page": per_page,
                "total_filtered": total_filtered, "total_pages": total_pages
            }
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    """Lightweight stats for dashboard header cards."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            c1 = await db.execute("SELECT COUNT(*) FROM messages")
            total = (await c1.fetchone())[0]

            c2 = await db.execute("SELECT COUNT(*) FROM messages WHERE date(timestamp) = date('now')")
            today = (await c2.fetchone())[0]

            c3 = await db.execute("SELECT COUNT(DISTINCT symbol) FROM messages WHERE symbol IS NOT NULL AND symbol != ''")
            unique = (await c3.fetchone())[0]

            c4 = await db.execute("SELECT timestamp FROM messages ORDER BY timestamp DESC LIMIT 1")
            last_row = await c4.fetchone()
            last_time = last_row[0] if last_row else None

            return {"success": True, "total_messages": total, "today_messages": today, "unique_symbols": unique, "last_message_time": last_time}
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sectors")
async def get_sectors():
    """Distinct sector list from messages."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT DISTINCT sector FROM messages WHERE sector IS NOT NULL AND TRIM(sector) != '' ORDER BY sector")
            rows = await cursor.fetchall()
            return {"success": True, "sectors": [r[0] for r in rows]}
    except Exception as e:
        logger.error(f"Error fetching sectors: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stocks")
async def get_stocks(active_only: bool = True):
    """Get all stocks from master table."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            query = "SELECT * FROM stocks"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY symbol ASC"
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            stocks = [dict(zip(columns, row)) for row in rows]
            return {"success": True, "stocks": stocks}
    except Exception as e:
        logger.error(f"Error fetching stocks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/import_scrip_master")
async def import_scrip_master(file: UploadFile = File(...), exchange: str = "NSE"):
    """Import Kotak scrip master Excel/CSV to populate nse_token/bse_token in stocks table."""
    try:
        content = await file.read()
        if file.filename.lower().endswith('.csv'):
            df = pd.read_csv(pd.io.common.BytesIO(content))
        else:
            df = pd.read_excel(pd.io.common.BytesIO(content))

        df.columns = [c.strip() for c in df.columns]
        cols_lower = {c.lower(): c for c in df.columns}

        sym_col = cols_lower.get("trading_symbol") or cols_lower.get("tradingsymbol") or cols_lower.get("symbol") or cols_lower.get("nse code") or cols_lower.get("nse symbol")
        token_col = cols_lower.get("exchange_token") or cols_lower.get("exchangetoken") or cols_lower.get("token") or cols_lower.get("instrument_token")
        isin_col = cols_lower.get("isin") or cols_lower.get("isin_code")
        name_col = cols_lower.get("company_name") or cols_lower.get("name") or cols_lower.get("company") or cols_lower.get("instrument_name")

        if not sym_col or not token_col:
            available = list(df.columns)
            return {"success": False, "message": f"Could not find symbol/token columns. Available: {available}"}

        token_field = "nse_token" if exchange.upper() == "NSE" else "bse_token"
        now_iso = get_ist_now().isoformat()
        updated = 0
        inserted = 0

        async with aiosqlite.connect(DB_PATH) as db:
            for _, row in df.iterrows():
                sym = str(row.get(sym_col, "")).strip().upper()
                if not sym or sym == "NAN":
                    continue
                try:
                    token = int(float(row.get(token_col, 0)))
                except (ValueError, TypeError):
                    continue
                if token <= 0:
                    continue

                isin_val = str(row.get(isin_col, "")).strip() if isin_col else None
                if isin_val == "nan" or isin_val == "":
                    isin_val = None
                name_val = str(row.get(name_col, "")).strip() if name_col else None
                if name_val == "nan" or name_val == "":
                    name_val = None

                cursor = await db.execute("SELECT id FROM stocks WHERE symbol = ?", (sym,))
                existing = await cursor.fetchone()
                if existing:
                    updates = [f"{token_field} = ?"]
                    params = [token]
                    if isin_val:
                        updates.append("isin = ?")
                        params.append(isin_val)
                    if name_val:
                        updates.append("company_name = COALESCE(NULLIF(company_name, ''), ?)")
                        params.append(name_val)
                    updates.append("updated_at = ?")
                    params.append(now_iso)
                    params.append(existing[0])
                    await db.execute(f"UPDATE stocks SET {', '.join(updates)} WHERE id = ?", params)
                    updated += 1
                else:
                    await db.execute(
                        f"INSERT INTO stocks (symbol, company_name, exchange, {token_field}, isin, is_active, added_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                        (sym, name_val, exchange.upper(), token, isin_val, now_iso, now_iso)
                    )
                    inserted += 1
            await db.commit()

        logger.info(f"Scrip master import ({exchange}): {updated} updated, {inserted} inserted from {file.filename}")
        return {"success": True, "exchange": exchange, "updated": updated, "inserted": inserted, "filename": file.filename}

    except Exception as e:
        logger.error(f"Error importing scrip master: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/quarterly_results")
async def get_quarterly_results(symbol: str = None, financial_year: str = None, limit: int = 200):
    """Get quarterly results for Analytics PE Analysis."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            query = "SELECT * FROM quarterly_results"
            params = []
            conditions = []

            if symbol:
                conditions.append("stock_symbol = ?")
                params.append(symbol)
            if financial_year:
                conditions.append("financial_year = ?")
                params.append(financial_year)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY updated_at DESC"
            if limit > 0:
                query += " LIMIT ?"
                params.append(limit)

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]

            results = []
            for row in rows:
                r = dict(zip(columns, row))
                if r.get('standalone_data'):
                    try:
                        r['standalone_data'] = json.loads(r['standalone_data'])
                    except Exception:
                        pass
                if r.get('consolidated_data'):
                    try:
                        r['consolidated_data'] = json.loads(r['consolidated_data'])
                    except Exception:
                        pass
                if r.get('raw_ai_response'):
                    try:
                        r['raw_ai_response'] = json.loads(r['raw_ai_response'])
                    except Exception:
                        pass
                results.append(r)

            return {"success": True, "results": results, "total": len(results)}
    except Exception as e:
        logger.error(f"Error fetching quarterly results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pe_analysis")
async def get_pe_analysis(fetch_cmp: bool = False, symbols: str = ""):
    """PE Analysis: one row per stock (latest non-FY quarter), consolidated-first FY EPS, optional live CMP + PE.
    symbols: comma-separated stock symbols to fetch CMP for (empty = all with valid EPS)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT
                    qr.stock_symbol,
                    qr.company_name,
                    qr.quarter,
                    qr.financial_year,
                    COALESCE(qr.eps_diluted_consolidated, qr.eps_basic_consolidated,
                             qr.eps_diluted_standalone, qr.eps_basic_standalone) AS qtr_eps,
                    COALESCE(qr.fy_eps_diluted_consolidated, qr.fy_eps_basic_consolidated,
                             qr.fy_eps_diluted_standalone, qr.fy_eps_basic_standalone) AS fy_eps,
                    CASE
                        WHEN qr.fy_eps_diluted_consolidated IS NOT NULL THEN qr.fy_eps_formula_consolidated
                        WHEN qr.fy_eps_basic_consolidated IS NOT NULL THEN qr.fy_eps_formula_consolidated
                        ELSE qr.fy_eps_formula_standalone
                    END AS fy_eps_formula,
                    CASE
                        WHEN qr.fy_eps_diluted_consolidated IS NOT NULL THEN 'C'
                        WHEN qr.fy_eps_basic_consolidated IS NOT NULL THEN 'C'
                        ELSE 'S'
                    END AS eps_basis,
                    qr.units,
                    qr.updated_at,
                    qr.cmp AS stored_cmp,
                    qr.pe AS stored_pe,
                    qr.cmp_updated_at,
                    qr.source_pdf_url,
                    qr.valuation,
                    s.sector,
                    s.exchange
                FROM quarterly_results qr
                LEFT JOIN stocks s ON s.symbol = qr.stock_symbol
                WHERE qr.quarter NOT IN ('FY')
                AND qr.id IN (
                    SELECT id FROM quarterly_results q2
                    WHERE q2.stock_symbol = qr.stock_symbol
                    AND q2.quarter NOT IN ('FY')
                    ORDER BY q2.financial_year DESC, q2.quarter DESC
                    LIMIT 1
                )
                ORDER BY qr.updated_at DESC
            """)
            rows = await cursor.fetchall()

            # Fetch per-quarter EPS + cumulative EPS for all stocks/FYs (for formula variants)
            quarters_map = {}
            sym_fy_set = set((r["stock_symbol"], r["financial_year"]) for r in rows)
            if sym_fy_set:
                where_parts = " OR ".join(["(stock_symbol = ? AND financial_year = ?)"] * len(sym_fy_set))
                flat_params = [v for pair in sym_fy_set for v in pair]
                qtr_cursor = await db.execute(f"""
                    SELECT stock_symbol, quarter, financial_year,
                           COALESCE(eps_diluted_consolidated, eps_basic_consolidated,
                                    eps_diluted_standalone, eps_basic_standalone) AS qtr_eps,
                           COALESCE(cumulative_eps_diluted_consolidated, cumulative_eps_basic_consolidated,
                                    cumulative_eps_diluted_standalone, cumulative_eps_basic_standalone) AS cum_eps
                    FROM quarterly_results
                    WHERE quarter NOT IN ('FY') AND ({where_parts})
                """, flat_params)
                for qr in await qtr_cursor.fetchall():
                    sym = qr["stock_symbol"]
                    if sym not in quarters_map:
                        quarters_map[sym] = {}
                    if qr["qtr_eps"] is not None:
                        quarters_map[sym][qr["quarter"]] = round(qr["qtr_eps"], 4)
                    if qr["cum_eps"] is not None:
                        n_key = {"Q1": "N3", "Q2": "N6", "Q3": "N9"}.get(qr["quarter"])
                        if n_key:
                            quarters_map[sym][n_key] = round(qr["cum_eps"], 4)

            # Fetch previous FY EPS + previous cumulative N9 for PFY/PN9/PQ4 formula variables
            prev_fy_map = {}
            sym_set = set(r["stock_symbol"] for r in rows)
            sym_fy_map = {r["stock_symbol"]: r["financial_year"] for r in rows}
            if sym_set:
                for sym in sym_set:
                    current_fy = sym_fy_map.get(sym)
                    if not current_fy:
                        continue
                    try:
                        prev_fy_str = str(int(current_fy) - 1)
                    except (ValueError, TypeError):
                        continue
                    pfy_cursor = await db.execute("""
                        SELECT quarter,
                               COALESCE(eps_diluted_consolidated, eps_basic_consolidated,
                                        eps_diluted_standalone, eps_basic_standalone) AS eps,
                               COALESCE(cumulative_eps_diluted_consolidated, cumulative_eps_basic_consolidated,
                                        cumulative_eps_diluted_standalone, cumulative_eps_basic_standalone) AS cum_eps
                        FROM quarterly_results
                        WHERE stock_symbol = ? AND financial_year = ?
                    """, (sym, prev_fy_str))
                    pfy_data = {}
                    for pr in await pfy_cursor.fetchall():
                        if pr["quarter"] == "FY" and pr["eps"] is not None:
                            pfy_data["PFY"] = round(pr["eps"], 4)
                        if pr["quarter"] == "Q3" and pr["cum_eps"] is not None:
                            pfy_data["PN9"] = round(pr["cum_eps"], 4)
                        if pr["quarter"] == "Q2" and pr["cum_eps"] is not None:
                            pfy_data["PN6"] = round(pr["cum_eps"], 4)
                    if pfy_data:
                        prev_fy_map[sym] = pfy_data

            # Merge prev FY data + compute fallback N values into quarters_map
            for sym in sym_set:
                if sym not in quarters_map:
                    quarters_map[sym] = {}
                qm = quarters_map[sym]
                # Fallback: compute N from individual quarters if AI didn't extract cumulative
                if "N3" not in qm and qm.get("Q1") is not None:
                    qm["N3"] = round(qm["Q1"], 4)
                if "N6" not in qm and qm.get("Q1") is not None and qm.get("Q2") is not None:
                    qm["N6"] = round(qm["Q1"] + qm["Q2"], 4)
                if "N9" not in qm and qm.get("Q1") is not None and qm.get("Q2") is not None and qm.get("Q3") is not None:
                    qm["N9"] = round(qm["Q1"] + qm["Q2"] + qm["Q3"], 4)
                # Add previous FY data
                pfy = prev_fy_map.get(sym, {})
                for k, v in pfy.items():
                    qm[k] = v
                # Compute PQ4 = PFY - PN9
                if "PFY" in qm and "PN9" in qm:
                    qm["PQ4"] = round(qm["PFY"] - qm["PN9"], 4)

        stock_data = []
        symbols_needing_cmp = []
        sym_exchange_map = {}
        for r in rows:
            qtr_eps = r["qtr_eps"]
            fy_eps = r["fy_eps"]
            fy_formula = r["fy_eps_formula"]
            eps_basis = r["eps_basis"]
            stored_cmp = r["stored_cmp"]
            stored_pe = r["stored_pe"]
            qtr_eps_rounded = round(qtr_eps, 2) if qtr_eps is not None else None
            fy_eps_rounded = round(fy_eps, 2) if fy_eps is not None else None

            pe_val = stored_pe
            if stored_cmp and fy_eps_rounded and fy_eps_rounded > 0 and not stored_pe:
                pe_val = round(stored_cmp / fy_eps_rounded, 2)

            stock_data.append({
                "stock_symbol": r["stock_symbol"],
                "company_name": r["company_name"],
                "quarter": r["quarter"],
                "financial_year": r["financial_year"],
                "qtr_eps": qtr_eps_rounded,
                "fy_eps": fy_eps_rounded,
                "fy_eps_formula": f"{fy_formula or ''} ({eps_basis})".strip(),
                "eps_basis": eps_basis,
                "units": r["units"],
                "sector": r["sector"],
                "exchange": r["exchange"],
                "cmp": round(stored_cmp, 2) if stored_cmp else None,
                "pe": pe_val,
                "cmp_updated_at": r["cmp_updated_at"],
                "updated_at": r["updated_at"],
                "source_pdf_url": r["source_pdf_url"],
                "valuation": r["valuation"],
                "quarters_eps": quarters_map.get(r["stock_symbol"], {}),
            })
            if fetch_cmp:
                symbols_needing_cmp.append(r["stock_symbol"])
                sym_exchange_map[r["stock_symbol"]] = r["exchange"] or "NSE"

        # Fetch live CMP from Kotak API — route NSE vs BSE
        cmp_map = {}
        cmp_error = None
        if fetch_cmp and not symbols_needing_cmp:
            cmp_error = "No stocks with valid FY EPS to fetch CMP for"
        elif fetch_cmp and symbols_needing_cmp:
            session_file = "kotak_session.json"
            session_valid = False
            if not os.path.exists(session_file):
                cmp_error = "No active session — please verify TOTP first"
            else:
                try:
                    async with aiofiles.open(session_file, 'r') as f:
                        sess = json.loads(await f.read())
                    exp = parse_datetime_ist(sess.get("expires_at", ""))
                    if not exp or get_ist_now() >= exp:
                        cmp_error = "Session expired — please verify TOTP again"
                    else:
                        session_valid = True
                except Exception:
                    cmp_error = "Invalid session — please verify TOTP"

            if session_valid:
                requested_set = set(s.strip() for s in symbols.split(",") if s.strip()) if symbols else None
                if requested_set:
                    symbols_needing_cmp = [s for s in symbols_needing_cmp if s in requested_set]

                nse_syms = [s for s in symbols_needing_cmp if sym_exchange_map.get(s, "NSE").upper() == "NSE"]
                bse_syms = [s for s in symbols_needing_cmp if sym_exchange_map.get(s, "NSE").upper() == "BSE"]

                async def _fetch_cmp_nse(syms):
                    """Fetch CMP for NSE symbols via token map lookup."""
                    result_map = {}
                    if not syms:
                        return result_map
                    tmap = await _fetch_nse_token_map()
                    tokens_to_fetch = []
                    token_to_symbol = {}
                    for sym in syms:
                        token = tmap.get(sym)
                        if token:
                            tokens_to_fetch.append(f"nse_cm|{token}")
                            token_to_symbol[str(token)] = sym
                    if not tokens_to_fetch:
                        return result_map
                    from get_quote import get_quotes_with_rate_limit, flatten_quote_result_list
                    batches = [",".join(tokens_to_fetch[i:i+190]) for i in range(0, len(tokens_to_fetch), 190)]
                    raw_results = await get_quotes_with_rate_limit(batches, requests_per_minute=190)
                    flattened = await flatten_quote_result_list(raw_results)
                    for q in flattened:
                        if q.get("error"):
                            continue
                        close_price = q.get("ohlc", {}).get("close")
                        token_val = str(q.get("exchange_token", ""))
                        if close_price and token_val in token_to_symbol:
                            cmp_raw = float(close_price)
                            result_map[token_to_symbol[token_val]] = cmp_raw / 100 if cmp_raw > 100000 else cmp_raw
                    logger.info(f"PE Analysis (nse_cm): fetched CMP for {len(result_map)}/{len(tokens_to_fetch)} stocks")
                    return result_map

                async def _fetch_cmp_bse(syms):
                    """Fetch CMP for BSE symbols — symbol IS the token (scrip code)."""
                    result_map = {}
                    if not syms:
                        return result_map
                    tokens_to_fetch = []
                    token_to_symbol = {}
                    for sym in syms:
                        tokens_to_fetch.append(f"bse_cm|{sym}")
                        token_to_symbol[sym] = sym
                    from get_quote import get_quotes_with_rate_limit, flatten_quote_result_list
                    batches = [",".join(tokens_to_fetch[i:i+190]) for i in range(0, len(tokens_to_fetch), 190)]
                    raw_results = await get_quotes_with_rate_limit(batches, requests_per_minute=190)
                    flattened = await flatten_quote_result_list(raw_results)
                    for q in flattened:
                        if q.get("error"):
                            continue
                        close_price = q.get("ohlc", {}).get("close")
                        ex_token = str(q.get("exchange_token", ""))
                        matched_sym = token_to_symbol.get(ex_token)
                        if close_price and matched_sym:
                            cmp_raw = float(close_price)
                            result_map[matched_sym] = cmp_raw / 100 if cmp_raw > 100000 else cmp_raw
                    logger.info(f"PE Analysis (bse_cm): fetched CMP for {len(result_map)}/{len(tokens_to_fetch)} stocks")
                    return result_map

                try:
                    nse_map, bse_map = await asyncio.gather(
                        _fetch_cmp_nse(nse_syms),
                        _fetch_cmp_bse(bse_syms),
                    )
                    cmp_map.update(nse_map)
                    cmp_map.update(bse_map)

                    if cmp_map:
                        now_iso = get_ist_now().isoformat()
                        async with aiosqlite.connect(DB_PATH) as db:
                            for sym, cmp_val in cmp_map.items():
                                eps_for_sym = next((s["fy_eps"] for s in stock_data if s["stock_symbol"] == sym), None)
                                pe_computed = round(cmp_val / eps_for_sym, 2) if eps_for_sym and eps_for_sym > 0 else None
                                await db.execute(
                                    """UPDATE quarterly_results SET cmp = ?, pe = ?, cmp_updated_at = ?
                                       WHERE id = (
                                           SELECT id FROM quarterly_results
                                           WHERE stock_symbol = ? AND quarter != 'FY'
                                           ORDER BY financial_year DESC, quarter DESC LIMIT 1
                                       )""",
                                    (cmp_val, pe_computed, now_iso, sym)
                                )
                            await db.commit()

                    no_token_count = len(symbols_needing_cmp) - len(cmp_map)
                    if no_token_count > 0 and not cmp_map:
                        cmp_error = f"No instrument tokens found for {no_token_count} symbols"
                except Exception as e:
                    logger.warning(f"CMP fetch failed: {e}")
                    cmp_error = f"CMP fetch failed: {str(e)}"

        # Merge live CMP into results + compute PE
        for item in stock_data:
            live_cmp = cmp_map.get(item["stock_symbol"])
            if live_cmp:
                item["cmp"] = round(live_cmp, 2)
                if item["fy_eps"] and item["fy_eps"] > 0:
                    item["pe"] = round(live_cmp / item["fy_eps"], 2)

        resp = {"success": True, "results": stock_data, "total": len(stock_data)}
        if cmp_error:
            resp["cmp_error"] = cmp_error
        if fetch_cmp and cmp_map:
            resp["cmp_fetched"] = len(cmp_map)
        return resp
    except Exception as e:
        logger.error(f"Error in PE analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PEEditRequest(BaseModel):
    quarter: str = None
    financial_year: str = None
    qtr_eps: float = None
    fy_eps: float = None
    cmp: float = None
    sector: str = None
    exchange: str = None
    valuation: str = None
    eps_basis: str = None
    old_quarter: str = None
    old_financial_year: str = None


@app.put("/api/pe_analysis/{stock_symbol}")
async def update_pe_analysis_row(stock_symbol: str, body: PEEditRequest):
    """Update editable fields of a PE Analysis row."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            match_q = body.old_quarter or body.quarter
            match_fy = body.old_financial_year or body.financial_year
            if not match_q or not match_fy:
                raise HTTPException(status_code=400, detail="quarter and financial_year required")

            sets = []
            params = []
            now_iso = get_ist_now().isoformat()

            if body.quarter is not None:
                sets.append("quarter = ?")
                params.append(body.quarter)
            if body.financial_year is not None:
                sets.append("financial_year = ?")
                params.append(body.financial_year)

            basis = (body.eps_basis or "C").upper()
            if body.qtr_eps is not None:
                if basis == "S":
                    sets.append("eps_diluted_standalone = ?")
                else:
                    sets.append("eps_diluted_consolidated = ?")
                params.append(body.qtr_eps)

            if body.fy_eps is not None:
                if basis == "S":
                    sets.append("fy_eps_diluted_standalone = ?")
                else:
                    sets.append("fy_eps_diluted_consolidated = ?")
                params.append(body.fy_eps)

            if body.cmp is not None:
                sets.append("cmp = ?")
                params.append(body.cmp)

            if body.valuation is not None:
                sets.append("valuation = ?")
                params.append(body.valuation if body.valuation else None)

            pe_val = None
            cmp_for_pe = body.cmp
            fy_for_pe = body.fy_eps
            if cmp_for_pe and fy_for_pe and fy_for_pe > 0:
                pe_val = round(cmp_for_pe / fy_for_pe, 2)
                sets.append("pe = ?")
                params.append(pe_val)
            elif body.cmp is not None or body.fy_eps is not None:
                # Fetch missing value from DB to recompute
                row = await db.execute(
                    "SELECT cmp, COALESCE(fy_eps_diluted_consolidated, fy_eps_basic_consolidated, fy_eps_diluted_standalone, fy_eps_basic_standalone) as fy FROM quarterly_results WHERE stock_symbol = ? AND quarter = ? AND financial_year = ?",
                    (stock_symbol, match_q, match_fy)
                )
                existing = await row.fetchone()
                if existing:
                    c = body.cmp if body.cmp is not None else (existing[0] or 0)
                    f = body.fy_eps if body.fy_eps is not None else (existing[1] or 0)
                    if c and f and f > 0:
                        pe_val = round(c / f, 2)
                        sets.append("pe = ?")
                        params.append(pe_val)

            if sets:
                sets.append("updated_at = ?")
                params.append(now_iso)
                params.extend([stock_symbol, match_q, match_fy])
                await db.execute(
                    f"UPDATE quarterly_results SET {', '.join(sets)} WHERE stock_symbol = ? AND quarter = ? AND financial_year = ?",
                    params
                )

            if body.exchange is not None:
                sets_qr = []
                sets_qr.append(("exchange", body.exchange))
                await db.execute(
                    "UPDATE quarterly_results SET exchange = ?, updated_at = ? WHERE stock_symbol = ? AND quarter = ? AND financial_year = ?",
                    (body.exchange, now_iso, stock_symbol, match_q, match_fy)
                )
                await db.execute(
                    "UPDATE stocks SET exchange = ?, updated_at = ? WHERE symbol = ?",
                    (body.exchange, now_iso, stock_symbol)
                )

            if body.sector is not None:
                await db.execute(
                    "UPDATE stocks SET sector = ?, updated_at = ? WHERE symbol = ?",
                    (body.sector, now_iso, stock_symbol)
                )

            await db.commit()

        return {"success": True, "stock_symbol": stock_symbol, "pe": pe_val}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating PE row for {stock_symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/pe_analysis/{stock_symbol}")
async def delete_pe_analysis_row(stock_symbol: str, quarter: str = "", financial_year: str = ""):
    """Delete a quarterly_results row by stock_symbol + quarter + financial_year."""
    if not quarter or not financial_year:
        raise HTTPException(status_code=400, detail="quarter and financial_year required")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM quarterly_results WHERE stock_symbol = ? AND quarter = ? AND financial_year = ?",
                (stock_symbol, quarter, financial_year)
            )
            await db.commit()
            if cursor.rowcount == 0:
                return {"success": False, "detail": "Row not found"}
            logger.info(f"Deleted PE row: {stock_symbol} {quarter} {financial_year}")
            return {"success": True, "deleted": 1}
    except Exception as e:
        logger.error(f"Error deleting PE row {stock_symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pe_sectors")
async def get_pe_sectors():
    """Distinct sector list from stocks table for PE edit dropdown."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL AND TRIM(sector) != '' ORDER BY sector"
            )
            rows = await cursor.fetchall()
            return {"success": True, "sectors": [r[0] for r in rows]}
    except Exception as e:
        logger.error(f"Error fetching PE sectors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pe_formulas")
async def get_pe_formulas():
    """List all saved PE formulas."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM pe_formulas ORDER BY is_default DESC, name")
        formulas = [dict(r) for r in await cursor.fetchall()]
    return {"success": True, "formulas": formulas}


@app.post("/api/pe_formulas")
async def create_pe_formula(body: dict):
    """Create a new PE formula."""
    import re
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Formula name is required")
    expr_pattern = re.compile(r'^[QNPFY\d\s+\-*/().]+$')
    for key in ("q1_expr", "q2_expr", "q3_expr", "q4_expr"):
        val = (body.get(key) or "").strip()
        if not val:
            raise HTTPException(status_code=400, detail=f"{key} is required")
        if not expr_pattern.match(val):
            raise HTTPException(status_code=400, detail=f"Invalid characters in {key}")
    now_iso = get_ist_now().isoformat()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO pe_formulas (name, q1_expr, q2_expr, q3_expr, q4_expr, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """, (name, body["q1_expr"].strip(), body["q2_expr"].strip(),
                  body["q3_expr"].strip(), body["q4_expr"].strip(), now_iso, now_iso))
            await db.commit()
        return {"success": True}
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=400, detail="Formula name already exists")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/pe_formulas/{formula_id}")
async def delete_pe_formula(formula_id: int):
    """Delete a custom PE formula (cannot delete the default)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT is_default FROM pe_formulas WHERE id = ?", (formula_id,))
        formula = await cursor.fetchone()
        if not formula:
            raise HTTPException(status_code=404, detail="Formula not found")
        if formula["is_default"]:
            raise HTTPException(status_code=400, detail="Cannot delete the default formula")
        await db.execute("DELETE FROM pe_formulas WHERE id = ?", (formula_id,))
        await db.commit()
    return {"success": True}


async def process_local_pdf_async_optimized(pdf_path: str):
    """PyMuPDF-based PDF processing for general financial analysis (replaces Poppler + docTR OCR)."""
    try:
        start_time = time.time()
        logger.info(f"Starting PyMuPDF PDF processing: {pdf_path}")

        encoded_images = await _extract_financial_pages_as_b64(pdf_path)
        if not encoded_images:
            logger.warning("No financial pages found in PDF")
            return None

        financial_metrics = await _call_openai_vision_general(encoded_images)

        total_time = time.time() - start_time
        logger.info(f"PDF processing completed in {total_time:.2f}s")
        return financial_metrics

    except Exception as e:
        logger.error(f"Error in PDF processing: {str(e)}")
        return None

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

@app.post("/api/test_quarterly_extract")
async def test_quarterly_extract(file: UploadFile = File(...)):
    """Test quarterly results extraction from PDF — returns AI result, does NOT store in DB."""
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, file.filename)

        async with aiofiles.open(temp_file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)

        logger.info(f"[TEST] Quarterly extraction for: {file.filename}")

        encoded_images = await _extract_financial_pages_as_b64(temp_file_path)
        if not encoded_images:
            raise HTTPException(status_code=422, detail="No financial pages detected in PDF")

        ai_response = await _call_openai_vision_quarterly(encoded_images)

        try:
            await aiofiles.os.remove(temp_file_path)
        except Exception:
            pass

        return {
            "success": True,
            "filename": file.filename,
            "financial_pages_found": len(encoded_images),
            "images_sent_to_ai": len(encoded_images),
            "quarterly_results": ai_response
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TEST] Quarterly extraction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload_quarterly_pdf")
async def upload_quarterly_pdf(file: UploadFile = File(...), stock_symbol: str = Form(...), exchange: str = Form("NSE")):
    """Upload a quarterly result PDF, run PyMuPDF + AI extraction, and save to quarterly_results DB."""
    try:
        stock_symbol = stock_symbol.strip().upper()
        if not stock_symbol:
            raise HTTPException(status_code=400, detail="stock_symbol is required")
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, file.filename)

        async with aiofiles.open(temp_file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)

        logger.info(f"[UPLOAD] Quarterly extraction for {stock_symbol}: {file.filename}")

        encoded_images = await _extract_financial_pages_as_b64(temp_file_path)
        if not encoded_images:
            raise HTTPException(status_code=422, detail="No financial pages detected in PDF")

        ai_response = await _call_openai_vision_quarterly(encoded_images)
        result = await process_quarterly_results(ai_response, stock_symbol, exchange=exchange)
        stored = result.get("stored", [])
        cmp_result = result.get("cmp_result", {})

        try:
            await aiofiles.os.remove(temp_file_path)
        except Exception:
            pass

        resp = {
            "success": True,
            "stock_symbol": stock_symbol,
            "filename": file.filename,
            "periods_stored": len(stored),
            "quarterly_results": ai_response,
        }
        if cmp_result.get("cmp"):
            resp["cmp"] = cmp_result["cmp"]
            resp["pe"] = cmp_result["pe"]
        if cmp_result.get("error"):
            resp["cmp_hint"] = cmp_result["error"]
        return resp

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UPLOAD] Quarterly extraction error for {stock_symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        
        # Parse expiry time using IST-aware helper
        expires_at = parse_datetime_ist(expires_at_str)
        
        if not expires_at:
            return {
                "session_active": False,
                "message": "Invalid expiry datetime"
            }
        
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

def _write_df_to_gsheet(spreadsheet, gid: str, df, label: str) -> int:
    """Write a DataFrame to a Google Sheet tab identified by gid. Returns row count written."""
    import numpy as np
    worksheet = None
    for sheet in spreadsheet.worksheets():
        if str(sheet.id) == gid:
            worksheet = sheet
            break
    if not worksheet:
        logger.error(f"Scrip master: worksheet gid={gid} not found for {label}")
        return 0
    data = [df.columns.tolist()] + df.values.tolist()
    data = [['' if (isinstance(cell, float) and np.isnan(cell)) else cell for cell in row] for row in data]
    new_row_count = len(data)
    old_row_count = worksheet.row_count
    col_count = max(worksheet.col_count, len(data[0]))
    if old_row_count != new_row_count or worksheet.col_count != col_count:
        worksheet.resize(rows=new_row_count, cols=col_count)
    worksheet.update('A1', data)
    logger.info(f"Scrip master: {label} written ({new_row_count - 1} rows) to gid={gid}")
    return new_row_count - 1


async def _download_and_write_scrip_masters(return_counts: bool = False):
    """Download NSE + BSE CM scrip master CSVs from Kotak API and write to Google Sheets.
    Returns {nse_count, bse_count, error} if return_counts=True, else None."""
    global _nse_token_cache, _bse_token_cache
    result = {"nse_count": 0, "bse_count": 0, "error": None}
    try:
        session_file = "kotak_session.json"
        if not os.path.exists(session_file):
            result["error"] = "Session file not found"
            logger.error(f"Scrip master: {result['error']}")
            return result if return_counts else None

        async with aiofiles.open(session_file, 'r') as f:
            content = await f.read()
            session_data = json.loads(content)

        base_url = session_data.get('base_url')
        access_token = session_data.get('access_token')
        if not base_url or not access_token:
            result["error"] = "base_url or access_token not found in session"
            logger.error(f"Scrip master: {result['error']}")
            return result if return_counts else None

        url = f"{base_url}/script-details/1.0/masterscrip/file-paths"
        headers = {'accept': '*/*', 'Authorization': access_token}

        async with httpx.AsyncClient(verify=False, timeout=60, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                result["error"] = f"Failed to fetch file paths: HTTP {response.status_code}"
                logger.error(f"Scrip master: {result['error']}")
                return result if return_counts else None

            file_paths = response.json().get('data', {}).get('filesPaths', [])

            nse_cm_url = None
            bse_cm_url = None
            for path in file_paths:
                if 'nse_cm-v1.csv' in path:
                    nse_cm_url = path
                if 'bse_cm-v1.csv' in path:
                    bse_cm_url = path

            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name('google_sheets_credentials.json', scope)
            gsheet_client = gspread.authorize(creds)
            spreadsheet = gsheet_client.open_by_key("1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM")

            # --- NSE CM ---
            if nse_cm_url:
                logger.info(f"Scrip master: Downloading NSE CM from {nse_cm_url}")
                csv_resp = await client.get(nse_cm_url)
                if csv_resp.status_code == 200:
                    df_nse = pd.read_csv(io.StringIO(csv_resp.text))
                    if 'pGroup' in df_nse.columns:
                        df_nse = df_nse[df_nse['pGroup'] == 'EQ'].copy()
                    result["nse_count"] = _write_df_to_gsheet(spreadsheet, NSE_CM_NEO_GID, df_nse, "NSE CM")
                else:
                    logger.error(f"Scrip master: NSE CM download failed HTTP {csv_resp.status_code}")
            else:
                logger.warning("Scrip master: nse_cm-v1.csv not found in file paths")

            # --- BSE CM ---
            if bse_cm_url:
                logger.info(f"Scrip master: Downloading BSE CM from {bse_cm_url}")
                csv_resp = await client.get(bse_cm_url)
                if csv_resp.status_code == 200:
                    df_bse = pd.read_csv(io.StringIO(csv_resp.text))
                    if 'pGroup' in df_bse.columns:
                        orig = len(df_bse)
                        df_bse = df_bse[df_bse['pGroup'].isin(['A', 'B', 'T', 'M', 'MT', 'EQ'])].copy()
                        logger.info(f"Scrip master: BSE CM filtered {orig}→{len(df_bse)} tradeable group rows")
                    result["bse_count"] = _write_df_to_gsheet(spreadsheet, BSE_CM_NEO_GID, df_bse, "BSE CM")
                else:
                    logger.error(f"Scrip master: BSE CM download failed HTTP {csv_resp.status_code}")
            else:
                logger.warning("Scrip master: bse_cm-v1.csv not found in file paths")

            _nse_token_cache = {}
            _bse_token_cache = {}
            logger.info(f"Scrip master: Done. NSE={result['nse_count']}, BSE={result['bse_count']}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Scrip master fetch failed: {e}")
        logger.exception("   Traceback:")

    return result if return_counts else None


async def fetch_cm_data_background():
    """Background task to fetch NSE + BSE CM data and write to Google Sheets."""
    await _download_and_write_scrip_masters(return_counts=False)


@app.post("/api/refresh_scrip_master")
async def refresh_scrip_master():
    """Manually trigger download of NSE + BSE CM scrip master files and write to Google Sheets."""
    if not await _check_session_valid():
        return {"success": False, "error": "No active session — please verify TOTP first"}
    result = await _download_and_write_scrip_masters(return_counts=True)
    if result.get("error"):
        return {"success": False, "error": result["error"]}
    return {
        "success": True,
        "nse_count": result["nse_count"],
        "bse_count": result["bse_count"],
        "message": f"Scrip master refreshed: NSE={result['nse_count']}, BSE={result['bse_count']}",
    }


@app.post("/api/verify_totp")
async def verify_totp(request: TOTPRequest, background_tasks: BackgroundTasks):
    """Verify TOTP code and authenticate with Neo trading system"""
    try:
        access_token = os.getenv("NEO_ACCESS_TOKEN")
        mobile_number = os.getenv("MOBILE_NUMBER")
        ucc = os.getenv("UCC")
        mpin = os.getenv("MPIN")
        if not all([access_token, mobile_number, ucc, mpin]):
            logger.error("Missing NEO_ACCESS_TOKEN, MOBILE_NUMBER, UCC, or MPIN")
            return {
                "success": False,
                "message": "Server configuration error: Missing credentials"
            }
        logger.info(f"Starting Neo authentication with TOTP from UI: {request.totp_code}")
        session_data = await neo_main_login(mobile_number, ucc, request.totp_code, mpin, access_token)
        
        if session_data:
            logger.info("Neo authentication successful")
            
            # Trigger NSE + BSE CM scrip master fetch in background after successful auth
            background_tasks.add_task(fetch_cm_data_background)
            logger.info("Triggered NSE + BSE CM scrip master fetch in background")
            
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
                
                # Validate session first before starting
                session_file = "kotak_session.json"
                if not os.path.exists(session_file):
                    logger.error(f"[Job {job_id}] No session file found")
                    active_jobs[job_id].status = "failed"
                    active_jobs[job_id].progress = 0
                    active_jobs[job_id].message = "No active session - Please verify TOTP first to authenticate"
                    active_jobs[job_id].error = "Session not found. Authentication required."
                    active_jobs[job_id].completed_at = get_ist_now().isoformat()
                    
                    await ws_manager.broadcast_message({
                        "type": "job_failed",
                        "job": asdict(active_jobs[job_id])
                    })
                    return
                
                # Check if session is expired
                async with aiofiles.open(session_file, 'r') as f:
                    content = await f.read()
                    session_data = json.loads(content)
                
                expires_at_str = session_data.get('expires_at')
                if expires_at_str:
                    expires_at = parse_datetime_ist(expires_at_str)
                    
                    if expires_at and get_ist_now() >= expires_at:
                        logger.error(f"[Job {job_id}] Session expired")
                        active_jobs[job_id].status = "failed"
                        active_jobs[job_id].progress = 0
                        active_jobs[job_id].message = "Session expired - Please verify TOTP again to re-authenticate"
                        active_jobs[job_id].error = "Session expired. Please authenticate again."
                        active_jobs[job_id].completed_at = get_ist_now().isoformat()
                        
                        await ws_manager.broadcast_message({
                            "type": "job_failed",
                            "job": asdict(active_jobs[job_id])
                        })
                        return
                
                logger.info(f"[Job {job_id}] Session validated successfully")
                
                # Import order placement modules (use place_orders_with_rate_limit - 190/min)
                from place_order import get_gsheet_stocks_df as get_order_stocks, get_order_data, place_orders_with_rate_limit
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
                
                # Step 2: Create order data and filter penny stocks (20% progress)
                active_jobs[job_id].message = f"Creating orders for {total_stocks} stocks..."
                active_jobs[job_id].progress = 20
                
                # Filter out penny stocks (BUY ORDER <= 10)
                filtered_rows = []
                penny_stock_count = 0
                
                for row in all_rows:
                    buy_order_value = row.get('BUY ORDER')
                    
                    # Convert to numeric and check if > 10
                    try:
                        buy_price = float(buy_order_value) if buy_order_value else 0
                        if buy_price > 10:
                            filtered_rows.append(row)
                        else:
                            penny_stock_count += 1
                            logger.debug(f"Skipping penny stock: {row.get('STOCK_NAME', 'Unknown')} (BUY ORDER: {buy_price})")
                    except (ValueError, TypeError):
                        penny_stock_count += 1
                        logger.debug(f"Skipping invalid BUY ORDER: {row.get('STOCK_NAME', 'Unknown')}")
                
                logger.info(f"[Job {job_id}] Filtered stocks: {len(filtered_rows)} tradeable, {penny_stock_count} penny stocks (BUY ORDER ≤ ₹10) skipped")
                
                all_orders = await get_order_data(filtered_rows)
                total_orders = len(all_orders)
                
                logger.info(f"[Job {job_id}] Created {total_orders} orders ({len(filtered_rows)} stocks × 2 orders)")
                
                # Step 3: Place orders (185/min, 7.5% under Kotak 200/min)
                active_jobs[job_id].message = f"Placing {total_orders} orders (rate limited: 185/min)..."
                active_jobs[job_id].progress = 25
                
                all_results = await place_orders_with_rate_limit(all_orders, orders_per_minute=185, max_concurrent=2)
                
                # Step 4: Count successes (90% progress)
                active_jobs[job_id].message = "Processing results..."
                active_jobs[job_id].progress = 90
                
                successful = sum(1 for r in all_results if r and r.get('status') != 'error')
                failed = total_orders - successful
                
                logger.info(f"[Job {job_id}] Order summary: {successful}/{total_orders} successful")
                
                # Complete (100% progress)
                active_jobs[job_id].status = "completed"
                active_jobs[job_id].progress = 100
                
                # Create summary message
                if penny_stock_count > 0:
                    summary_msg = f"Orders executed: {successful} successful, {failed} failed. Skipped {penny_stock_count} penny stocks (BUY ORDER ≤ ₹10)"
                else:
                    summary_msg = f"All orders executed: {successful} successful, {failed} failed"
                
                active_jobs[job_id].message = summary_msg
                active_jobs[job_id].completed_at = get_ist_now().isoformat()
                active_jobs[job_id].result = {
                    "status": "completed",
                    "total_orders": total_orders,
                    "successful": successful,
                    "failed": failed,
                    "penny_stocks_skipped": penny_stock_count,
                    "tradeable_stocks": len(filtered_rows)
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
                
                # Validate session first before starting
                session_file = "kotak_session.json"
                if not os.path.exists(session_file):
                    logger.error(f"[Job {job_id}] No session file found")
                    active_jobs[job_id].status = "failed"
                    active_jobs[job_id].progress = 0
                    active_jobs[job_id].message = "No active session - Please verify TOTP first to authenticate"
                    active_jobs[job_id].error = "Session not found. Authentication required."
                    active_jobs[job_id].completed_at = get_ist_now().isoformat()
                    
                    await ws_manager.broadcast_message({
                        "type": "job_failed",
                        "job": asdict(active_jobs[job_id])
                    })
                    return
                
                # Check if session is expired
                async with aiofiles.open(session_file, 'r') as f:
                    content = await f.read()
                    session_data = json.loads(content)
                
                expires_at_str = session_data.get('expires_at')
                if expires_at_str:
                    expires_at = parse_datetime_ist(expires_at_str)
                    
                    if expires_at and get_ist_now() >= expires_at:
                        logger.error(f"[Job {job_id}] Session expired")
                        active_jobs[job_id].status = "failed"
                        active_jobs[job_id].progress = 0
                        active_jobs[job_id].message = "Session expired - Please verify TOTP again to re-authenticate"
                        active_jobs[job_id].error = "Session expired. Please authenticate again."
                        active_jobs[job_id].completed_at = get_ist_now().isoformat()
                        
                        await ws_manager.broadcast_message({
                            "type": "job_failed",
                            "job": asdict(active_jobs[job_id])
                        })
                        return
                
                logger.info(f"[Job {job_id}] Session validated successfully")
                
                # Import quote fetching modules (use get_quotes_with_rate_limit - 190 req/min)
                from get_quote import (
                    get_gsheet_stocks_df, get_symbol_from_gsheet_stocks_df,
                    flatten_quote_result_list, fetch_ohlc_from_quote_result,
                    update_df_with_quote_ohlc, write_quote_ohlc_to_gsheet,
                    get_quotes_with_rate_limit
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
                
                # Step 3: Fetch quotes with rate limiting (190 req/min)
                active_jobs[job_id].message = f"Fetching quotes for {total_symbols} stocks (rate limited: 190/min)..."
                active_jobs[job_id].progress = 15
                
                # Build symbol batches: each batch = 1 API call (190 symbols per call for efficiency)
                batch_size = 190
                symbol_batches = [
                    symbols_list[i:i + batch_size]
                    for i in range(0, total_symbols, batch_size)
                ]
                logger.info(f"[Job {job_id}] Will process {len(symbol_batches)} API requests (rate limited: 190/min)")
                
                all_quote_results = await get_quotes_with_rate_limit(symbol_batches, requests_per_minute=190)
                
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

@app.get("/api/auto_fetch_status")
async def get_auto_fetch_status():
    """Get auto fetch enabled status (from environment variable)"""
    return {
        "success": True,
        "auto_fetch_enabled": AUTO_FETCH_ENABLED
    }

@app.get("/api/scheduled_fetch_config")
async def get_scheduled_fetch_config():
    """Get current scheduled fetch configuration from config.json"""
    try:
        # Reload from file to get latest (in case file was edited manually)
        load_scheduled_fetch_config_sync()
        
        # Get last completion time from scheduled_fetch.log
        last_completion = None
        log_file = "scheduled_fetch.log"
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    # Search backwards for last COMPLETED entry
                    for line in reversed(lines):
                        if 'COMPLETED' in line:
                            # Extract timestamp from log line
                            # Format: 2026-01-02 09:15:31,456 - COMPLETED - 2026-01-02 09:15:31 IST
                            parts = line.split(' - ')
                            if len(parts) >= 2:
                                timestamp_part = parts[0].strip()
                                # Parse: 2026-01-02 09:15:31,456
                                try:
                                    dt_str = timestamp_part.split(',')[0]  # Remove milliseconds
                                    last_completion = dt_str
                                except:
                                    pass
                            break
            except Exception as e:
                logger.debug(f"Could not read scheduled_fetch.log: {e}")
        
        config_data = SCHEDULED_FETCH_CONFIG.copy()
        if last_completion:
            config_data['last_completion'] = last_completion
        
        return {
            "success": True,
            "config": config_data
        }
    except Exception as e:
        logger.error(f"Error getting scheduled fetch config: {e}")
        return {
            "success": False,
            "message": str(e)
        }

@app.put("/api/scheduled_fetch_config")
async def update_scheduled_fetch_config_endpoint(request: Request):
    """Update scheduled fetch configuration in config.json"""
    try:
        user = await verify_session(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        data = await request.json()
        
        # Validate input
        hour = int(data.get("hour", 12))
        minute = int(data.get("minute", 40))
        second = int(data.get("second", 0))
        enabled = bool(data.get("enabled", True))
        weekdays_only = bool(data.get("weekdays_only", True))
        
        if not (0 <= hour <= 23):
            raise HTTPException(status_code=400, detail="Hour must be between 0 and 23")
        if not (0 <= minute <= 59):
            raise HTTPException(status_code=400, detail="Minute must be between 0 and 59")
        if not (0 <= second <= 59):
            raise HTTPException(status_code=400, detail="Second must be between 0 and 59")
        
        config = {
            "enabled": enabled,
            "hour": hour,
            "minute": minute,
            "second": second,
            "weekdays_only": weekdays_only
        }
        
        success = await update_scheduled_fetch_config(config)
        
        if success:
            return {
                "success": True,
                "message": f"Scheduled fetch config updated in config.json: {hour:02d}:{minute:02d}:{second:02d} IST",
                "config": SCHEDULED_FETCH_CONFIG
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update config.json")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating scheduled fetch config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        

# ============================================================================
# LAST ACTIONS TRACKING (persistent timestamps for UI hints)
# ============================================================================

LAST_ACTIONS_FILE = "last_actions.json"

def load_last_actions() -> Dict:
    """Load last action timestamps from JSON file"""
    try:
        if os.path.exists(LAST_ACTIONS_FILE):
            with open(LAST_ACTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading last_actions.json: {e}")
    return {"last_quotes": None, "last_order": None}

def save_last_actions(actions: Dict) -> bool:
    """Save last action timestamps to JSON file"""
    try:
        with open(LAST_ACTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(actions, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving last_actions.json: {e}")
        return False

@app.get("/api/last_actions")
async def get_last_actions():
    """Get last action timestamps for quotes and orders"""
    try:
        actions = load_last_actions()
        return {
            "success": True,
            "last_quotes": actions.get("last_quotes"),
            "last_order": actions.get("last_order")
        }
    except Exception as e:
        logger.error(f"Error getting last actions: {e}")
        return {"success": False, "message": str(e)}

@app.post("/api/last_actions/{action_type}")
async def update_last_action(action_type: str):
    """Update last action timestamp (action_type: 'quotes' or 'order')"""
    try:
        if action_type not in ["quotes", "order"]:
            raise HTTPException(status_code=400, detail="Invalid action type. Use 'quotes' or 'order'")
        
        actions = load_last_actions()
        timestamp = get_ist_now().isoformat()
        
        if action_type == "quotes":
            actions["last_quotes"] = timestamp
        else:
            actions["last_order"] = timestamp
        
        save_last_actions(actions)
        
        logger.info(f"✅ Updated last_{action_type} timestamp: {timestamp}")
        
        return {
            "success": True,
            "action_type": action_type,
            "timestamp": timestamp
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating last action: {e}")
        return {"success": False, "message": str(e)}

# ============================================================================

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
    uvicorn.run(
        app, host="0.0.0.0", port=5000,
        ws_ping_interval=20, ws_ping_timeout=60
    )
