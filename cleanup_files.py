#!/usr/bin/env python3
"""
Manual File Cleanup Script
Efficiently removes old PDFs and images based on retention policies.

Usage:
    python cleanup_files.py              # Run with default settings
    python cleanup_files.py --dry-run    # Preview what would be deleted
    python cleanup_files.py --force      # Skip confirmation prompt
    python cleanup_files.py --all        # Delete all files regardless of age
"""

import asyncio
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import logging
from typing import Dict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Cleanup configuration (matches nse_url_test.py)
CLEANUP_CONFIG = {
    "pdf_retention_days": 30,      # Keep PDFs for 30 days
    "images_retention_days": 7,     # Keep images for 7 days
    "folders": {
        "pdf": "files/pdf",
        "images": "images",
        "downloads": "downloads",
        "temp_uploads": "temp_uploads"
    }
}


async def analyze_folder(folder_path: str, retention_days: int = None) -> Dict:
    """Analyze folder and return statistics without deleting."""
    stats = {
        "total_files": 0,
        "total_size_mb": 0,
        "old_files": 0,
        "old_size_mb": 0,
        "oldest_file": None,
        "newest_file": None
    }
    
    folder = Path(folder_path)
    if not folder.exists():
        return stats
    
    cutoff_time = None
    if retention_days is not None:
        cutoff_time = datetime.now() - timedelta(days=retention_days)
        cutoff_timestamp = cutoff_time.timestamp()
    
    for item in folder.rglob('*'):
        if item.is_file():
            file_size = item.stat().st_size
            file_mtime = item.stat().st_mtime
            file_date = datetime.fromtimestamp(file_mtime)
            
            stats["total_files"] += 1
            stats["total_size_mb"] += file_size / (1024 * 1024)
            
            # Track oldest and newest
            if stats["oldest_file"] is None or file_mtime < stats["oldest_file"][1]:
                stats["oldest_file"] = (item.name, file_mtime, file_date)
            if stats["newest_file"] is None or file_mtime > stats["newest_file"][1]:
                stats["newest_file"] = (item.name, file_mtime, file_date)
            
            # Count old files
            if retention_days is not None and file_mtime < cutoff_timestamp:
                stats["old_files"] += 1
                stats["old_size_mb"] += file_size / (1024 * 1024)
    
    return stats


async def cleanup_folder(folder_path: str, retention_days: int = None, dry_run: bool = False) -> Dict:
    """Cleanup files in folder based on retention policy."""
    stats = {
        "files_deleted": 0,
        "space_freed_mb": 0,
        "errors": 0
    }
    
    folder = Path(folder_path)
    if not folder.exists():
        logger.info(f"📁 Folder {folder_path} doesn't exist, skipping")
        return stats
    
    cutoff_time = None
    if retention_days is not None:
        cutoff_time = datetime.now() - timedelta(days=retention_days)
        cutoff_timestamp = cutoff_time.timestamp()
        logger.info(f"🧹 {'[DRY RUN] ' if dry_run else ''}Cleaning {folder_path} (files older than {retention_days} days)")
    else:
        logger.info(f"🧹 {'[DRY RUN] ' if dry_run else ''}Cleaning ALL files in {folder_path}")
    
    for item in folder.rglob('*'):
        if item.is_file():
            try:
                file_mtime = item.stat().st_mtime
                should_delete = retention_days is None or file_mtime < cutoff_timestamp
                
                if should_delete:
                    file_size = item.stat().st_size
                    file_date = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d')
                    
                    if not dry_run:
                        item.unlink()
                    
                    stats["files_deleted"] += 1
                    stats["space_freed_mb"] += file_size / (1024 * 1024)
                    
                    logger.debug(f"🗑️  {'[DRY RUN] ' if dry_run else ''}Deleted: {item.name} ({file_date}, {file_size / 1024:.1f} KB)")
                    
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"❌ Error processing {item}: {e}")
    
    # Clean up empty directories (only if not dry run)
    if not dry_run:
        for item in sorted(folder.rglob('*'), reverse=True):
            if item.is_dir() and not any(item.iterdir()):
                try:
                    item.rmdir()
                    logger.debug(f"📂 Removed empty directory: {item.name}")
                except Exception as e:
                    logger.debug(f"Could not remove directory {item}: {e}")
    
    logger.info(
        f"✅ {'[DRY RUN] ' if dry_run else ''}Cleanup complete for {folder_path}: "
        f"{stats['files_deleted']} files {'would be ' if dry_run else ''}deleted, "
        f"{stats['space_freed_mb']:.2f} MB {'would be ' if dry_run else ''}freed"
    )
    
    return stats


async def main():
    """Main cleanup execution."""
    parser = argparse.ArgumentParser(
        description='Manual file cleanup script for stock trading automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cleanup_files.py                    # Run with default settings
  python cleanup_files.py --dry-run          # Preview what would be deleted
  python cleanup_files.py --force            # Skip confirmation
  python cleanup_files.py --all              # Delete all files
  python cleanup_files.py --folder images    # Clean only images folder
        """
    )
    
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview what would be deleted without actually deleting')
    parser.add_argument('--force', action='store_true',
                       help='Skip confirmation prompt')
    parser.add_argument('--all', action='store_true',
                       help='Delete all files regardless of age')
    parser.add_argument('--folder', type=str, choices=['pdf', 'images', 'downloads', 'temp_uploads'],
                       help='Clean only specific folder')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    logger.info("=" * 70)
    logger.info("🧹 MANUAL FILE CLEANUP SCRIPT")
    logger.info("=" * 70)
    
    # Analyze all folders first
    logger.info("\n📊 ANALYZING FOLDERS...")
    logger.info("-" * 70)
    
    total_analysis = {
        "total_files": 0,
        "total_size_mb": 0,
        "old_files": 0,
        "old_size_mb": 0
    }
    
    folders_to_clean = {}
    
    if args.folder:
        # Clean only specific folder
        folders_to_clean[args.folder] = CLEANUP_CONFIG["folders"][args.folder]
    else:
        # Clean all folders
        folders_to_clean = CLEANUP_CONFIG["folders"]
    
    for folder_name, folder_path in folders_to_clean.items():
        retention_days = None if args.all else (
            CLEANUP_CONFIG["pdf_retention_days"] if folder_name == "pdf" else
            CLEANUP_CONFIG["images_retention_days"] if folder_name == "images" else
            CLEANUP_CONFIG["pdf_retention_days"] if folder_name == "downloads" else
            1  # temp_uploads
        )
        
        stats = await analyze_folder(folder_path, retention_days)
        
        if stats["total_files"] > 0:
            logger.info(f"\n📁 {folder_name.upper()} ({folder_path}):")
            logger.info(f"   Total files: {stats['total_files']} ({stats['total_size_mb']:.2f} MB)")
            
            if retention_days is not None:
                logger.info(f"   Files older than {retention_days} days: {stats['old_files']} ({stats['old_size_mb']:.2f} MB)")
            else:
                logger.info(f"   All files will be deleted: {stats['total_files']} ({stats['total_size_mb']:.2f} MB)")
            
            if stats["oldest_file"]:
                logger.info(f"   Oldest file: {stats['oldest_file'][0]} ({stats['oldest_file'][2].strftime('%Y-%m-%d')})")
            if stats["newest_file"]:
                logger.info(f"   Newest file: {stats['newest_file'][0]} ({stats['newest_file'][2].strftime('%Y-%m-%d')})")
            
            total_analysis["total_files"] += stats["total_files"]
            total_analysis["total_size_mb"] += stats["total_size_mb"]
            total_analysis["old_files"] += stats["old_files"]
            total_analysis["old_size_mb"] += stats["old_size_mb"]
    
    logger.info("\n" + "=" * 70)
    logger.info(f"📊 TOTAL SUMMARY:")
    logger.info(f"   Total files: {total_analysis['total_files']} ({total_analysis['total_size_mb']:.2f} MB)")
    logger.info(f"   Files to delete: {total_analysis['old_files']} ({total_analysis['old_size_mb']:.2f} MB)")
    logger.info("=" * 70)
    
    if total_analysis["old_files"] == 0:
        logger.info("\n✅ No files to clean up!")
        return
    
    # Confirmation prompt
    if not args.force and not args.dry_run:
        logger.info(f"\n⚠️  WARNING: This will delete {total_analysis['old_files']} files ({total_analysis['old_size_mb']:.2f} MB)")
        response = input("\nProceed with cleanup? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            logger.info("❌ Cleanup cancelled by user")
            return
    
    # Perform cleanup
    logger.info(f"\n{'🔍 DRY RUN MODE - NO FILES WILL BE DELETED' if args.dry_run else '🚀 STARTING CLEANUP...'}")
    logger.info("-" * 70)
    
    total_stats = {
        "files_deleted": 0,
        "space_freed_mb": 0,
        "errors": 0
    }
    
    for folder_name, folder_path in folders_to_clean.items():
        retention_days = None if args.all else (
            CLEANUP_CONFIG["pdf_retention_days"] if folder_name == "pdf" else
            CLEANUP_CONFIG["images_retention_days"] if folder_name == "images" else
            CLEANUP_CONFIG["pdf_retention_days"] if folder_name == "downloads" else
            1  # temp_uploads
        )
        
        stats = await cleanup_folder(folder_path, retention_days, args.dry_run)
        
        total_stats["files_deleted"] += stats["files_deleted"]
        total_stats["space_freed_mb"] += stats["space_freed_mb"]
        total_stats["errors"] += stats["errors"]
    
    logger.info("\n" + "=" * 70)
    logger.info(f"✅ {'DRY RUN ' if args.dry_run else ''}CLEANUP COMPLETED!")
    logger.info(f"   Files {'would be ' if args.dry_run else ''}deleted: {total_stats['files_deleted']}")
    logger.info(f"   Space {'would be ' if args.dry_run else ''}freed: {total_stats['space_freed_mb']:.2f} MB")
    if total_stats["errors"] > 0:
        logger.info(f"   Errors: {total_stats['errors']}")
    logger.info("=" * 70)
    
    if args.dry_run:
        logger.info("\n💡 Run without --dry-run to actually delete files")


if __name__ == "__main__":
    asyncio.run(main())

