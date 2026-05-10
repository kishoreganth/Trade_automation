#!/usr/bin/env python3
"""
Script to reset the messages database for the Stock Trading Dashboard
This will delete the existing database so it can be recreated with the new schema
"""

import os
import sys
import asyncio
import aiosqlite
from pathlib import Path

def reset_database():
    """Delete the existing database file"""
    db_path = Path(os.getenv('DB_PATH', 'messages.db'))
    
    if db_path.exists():
        try:
            os.remove(db_path)
            print("✅ Existing database deleted successfully")
            print("📝 The database will be recreated with the new schema when you start the dashboard")
        except Exception as e:
            print(f"❌ Error deleting database: {e}")
            return False
    else:
        print("ℹ️  No existing database found")
    
    return True

async def remove_test_messages():
    """Remove all messages where option is 'test' from the database"""
    db_path = Path(os.getenv('DB_PATH', 'messages.db'))
    
    if not db_path.exists():
        print("ℹ️  No database found")
        return False
    
    try:
        async with aiosqlite.connect(db_path) as db:
            # Count test messages before deletion
            cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE option = 'test'")
            count = (await cursor.fetchone())[0]
            
            if count == 0:
                print("ℹ️  No test messages found in database")
                return True
            
            # Delete test messages
            await db.execute("DELETE FROM messages WHERE option = 'test'")
            await db.commit()
            
            print(f"✅ Removed {count} test message(s) from database")
            return True
            
    except Exception as e:
        print(f"❌ Error removing test messages: {e}")
        return False

def remove_test_messages_sync():
    """Synchronous wrapper for remove_test_messages"""
    return asyncio.run(remove_test_messages())

def main():
    """Main function"""
    print("=" * 60)
    print("🗄️  DATABASE UTILITY")
    print("=" * 60)
    print("Choose an option:")
    print("1. Reset database (delete entire database file)")
    print("2. Remove test messages only (keep all other data)")
    print("=" * 60)
    
    choice = input("Enter your choice (1 or 2): ").strip()
    
    if choice == "1":
        print("\n⚠️  WARNING: This will delete the entire messages.db file")
        print("The database will be recreated with the new schema when you start the dashboard")
        response = input("Are you sure you want to reset the database? (y/N): ").lower().strip()
        
        if response in ['y', 'yes']:
            if reset_database():
                print("\n✅ Database reset complete!")
                print("💡 You can now start the dashboard with: python nse_url_test.py")
            else:
                print("\n❌ Database reset failed!")
                sys.exit(1)
        else:
            print("❌ Database reset cancelled")
    
    elif choice == "2":
        print("\n🧹 Removing test messages from database...")
        if remove_test_messages_sync():
            print("\n✅ Test messages removed successfully!")
        else:
            print("\n❌ Failed to remove test messages!")
            sys.exit(1)
    
    else:
        print("❌ Invalid choice. Please run again and select 1 or 2.")
        sys.exit(1)

if __name__ == "__main__":
    main()
