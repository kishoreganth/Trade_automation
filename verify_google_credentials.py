#!/usr/bin/env python3
"""
Verify Google Sheets credentials - check service account, expiry, and sheet access.
Run: python verify_google_credentials.py
"""
import json
import os
from pathlib import Path

CREDS_FILE = "google_sheets_credentials.json"
SHEET_ID = os.getenv("sheet_id", "1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM")
GID = os.getenv("sheet_gid", "1933500776")


def main():
    print("=" * 60)
    print("Google Sheets Credentials Verification")
    print("=" * 60)

    # 1. File exists
    if not Path(CREDS_FILE).exists():
        print(f"\n❌ FAIL: {CREDS_FILE} not found")
        print("   Download from GCP Console → IAM → Service Accounts → Keys")
        return
    print(f"\n✅ File exists: {CREDS_FILE}")

    # 2. Parse JSON
    try:
        with open(CREDS_FILE) as f:
            creds_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"\n❌ FAIL: Invalid JSON - {e}")
        return
    except Exception as e:
        print(f"\n❌ FAIL: Could not read file - {e}")
        return
    print("✅ Valid JSON")

    # 3. Required fields
    required = ["type", "project_id", "client_email", "private_key_id", "private_key"]
    missing = [f for f in required if not creds_data.get(f)]
    if missing:
        print(f"\n❌ FAIL: Missing fields: {missing}")
        return
    print("✅ All required fields present")

    # 4. Service account info
    email = creds_data.get("client_email", "")
    project = creds_data.get("project_id", "")
    key_id = creds_data.get("private_key_id", "")[:8] + "..."

    print(f"\n📋 Service Account:")
    print(f"   Email: {email}")
    print(f"   Project: {project}")
    print(f"   Key ID: {key_id}")

    # 5. Match expected
    expected = "stock-auto-service@spry-precinct-423711-b8.iam.gserviceaccount.com"
    if email != expected:
        print(f"\n⚠️  WARNING: Email mismatch!")
        print(f"   Expected: {expected}")
        print(f"   Got:      {email}")
        print("   Sheet must be shared with the email above (Got)")
    else:
        print(f"\n✅ Email matches expected: {expected}")

    # 6. Service account keys don't expire - no expiry field in JSON
    print("\n📋 Key expiry: Service account keys do NOT expire in JSON.")
    print("   They remain valid until revoked/rotated in GCP Console.")

    # 7. Test actual API access
    print("\n🔄 Testing API access...")
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
    except ImportError:
        print("   ⚠️  Install: pip install gspread oauth2client")
        return

    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SHEET_ID)
        worksheet = None
        for s in spreadsheet.worksheets():
            if str(s.id) == str(GID):
                worksheet = s
                break
        if not worksheet:
            worksheet = spreadsheet.get_worksheet(0)
        # Try read
        _ = worksheet.row_values(1)
        print(f"   ✅ Opened: {spreadsheet.title}")
        print(f"   ✅ Worksheet: {worksheet.title} (gid={worksheet.id})")
        print("\n✅ API ACCESS OK - Credentials work")
    except Exception as e:
        err = str(e)
        print(f"\n❌ API ACCESS FAILED: {err}")
        if "403" in err or "permission" in err.lower():
            print("\n   Fix: Share the sheet with the service account email above")
            print("   Or: Add to Shared Drive if sheet is in Shared Drive")
        elif "404" in err:
            print("\n   Fix: Check SHEET_ID and GID are correct")
    print("=" * 60)


if __name__ == "__main__":
    main()
