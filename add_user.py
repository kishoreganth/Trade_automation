#!/usr/bin/env python3
"""
Simple script to add users to the dashboard authentication system.
Usage: python add_user.py
"""
import asyncio
import aiosqlite
import hashlib
from datetime import datetime
import getpass

DB_PATH = "messages.db"

async def add_user():
    """Add a new user to the database"""
    print("=" * 50)
    print("Add New User to Dashboard")
    print("=" * 50)
    
    # Get username
    while True:
        username = input("\nEnter username: ").strip()
        if not username:
            print("❌ Username cannot be empty")
            continue
        if len(username) < 3:
            print("❌ Username must be at least 3 characters")
            continue
        break
    
    # Get password
    while True:
        password = getpass.getpass("Enter password: ")
        if not password:
            print("❌ Password cannot be empty")
            continue
        if len(password) < 6:
            print("❌ Password must be at least 6 characters")
            continue
        
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("❌ Passwords do not match")
            continue
        break
    
    # Hash password
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Check if username already exists
            cursor = await db.execute(
                "SELECT id FROM users WHERE username = ?", 
                (username,)
            )
            existing_user = await cursor.fetchone()
            
            if existing_user:
                print(f"\n❌ User '{username}' already exists!")
                return
            
            # Insert new user
            await db.execute("""
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
            """, (username, password_hash, datetime.now().isoformat()))
            
            await db.commit()
            
            print(f"\n✅ User '{username}' created successfully!")
            print(f"   They can now login at the dashboard with these credentials.")
            
    except Exception as e:
        print(f"\n❌ Error creating user: {e}")

async def list_users():
    """List all users in the database"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT username, created_at, last_login 
                FROM users 
                ORDER BY created_at DESC
            """)
            users = await cursor.fetchall()
            
            if not users:
                print("\n📋 No users found in database")
                return
            
            print("\n" + "=" * 70)
            print("Current Users")
            print("=" * 70)
            print(f"{'Username':<20} {'Created':<25} {'Last Login':<25}")
            print("-" * 70)
            
            for username, created_at, last_login in users:
                last_login_str = last_login if last_login else "Never"
                print(f"{username:<20} {created_at:<25} {last_login_str:<25}")
            
            print("=" * 70)
            
    except Exception as e:
        print(f"\n❌ Error listing users: {e}")

async def main():
    """Main menu"""
    while True:
        print("\n" + "=" * 50)
        print("Dashboard User Management")
        print("=" * 50)
        print("1. Add new user")
        print("2. List all users")
        print("3. Exit")
        print("=" * 50)
        
        choice = input("\nEnter your choice (1-3): ").strip()
        
        if choice == "1":
            await add_user()
        elif choice == "2":
            await list_users()
        elif choice == "3":
            print("\n👋 Goodbye!")
            break
        else:
            print("\n❌ Invalid choice. Please enter 1, 2, or 3.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted. Goodbye!")

