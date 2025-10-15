from neo_login.get_access_token import KotakAccessTokenClient
import asyncio
from neo_login.get_token_totp import KotakTOTPClient
from neo_login.get_final_session import KotakFinalSessionClient
from neo_login.session_manager import KotakSessionManager
import json
import os



from dotenv import load_dotenv
load_dotenv()


async def main(client_credentials, mobile_number, ucc, totp, mpin):
    """
    Main authentication flow with session management
    Checks for existing valid session first, then authenticates if needed
    """
    
    # Initialize session manager
    session_manager = KotakSessionManager()
    
    # Try to get existing valid session
    print("🔍 Checking for existing valid session...")
    existing_session = await session_manager.get_valid_session()
    
    if existing_session:
        print("✅ Found valid existing session!")
        print(f"Session ID: {existing_session.get('sid')}")
        print(f"Created at: {existing_session.get('created_at')}")
        print(f"Expires at: {existing_session.get('expires_at')}")
        
        # Get authentication headers for API calls
        auth_headers = await session_manager.get_session_headers()
        print("🔐 Authentication headers ready for API calls")
        return existing_session
    
    print("🚀 No valid session found. Starting fresh authentication...")
    
    ## STEP 1: Get access token
    print("📡 Step 1: Getting access token...")
    client = KotakAccessTokenClient(client_credentials)
    token_data = await client.get_access_token()

    if not token_data:
        print("❌ Failed to get access token")
        return None

    access_token = token_data["access_token"]
    print(token_data)
    session_manager.set_access_token(access_token)
    print(f"✅ Access token obtained: {access_token[:20]}...")
    
    ## STEP 2: TOTP Login
    print("🔐 Step 2: TOTP authentication...")
    # mobile_number = os.getenv("MOBILE_NUMBER")
    # ucc = os.getenv("UCC")
    # totp = os.getenv("TOTP")
    
    # Debug environment variables
    print(f"🔍 Environment variables check:")
    print(f"   MOBILE_NUMBER: {'✅ Found' if mobile_number else '❌ Missing'}")
    print(f"   UCC: {'✅ Found' if ucc else '❌ Missing'}")
    print(f"   TOTP: {'✅ Found' if totp else '❌ Missing'}")
    
    if not all([mobile_number, ucc, totp]):
        print("❌ Missing required environment variables!")
        print("\n🔧 Troubleshooting steps:")
        print("1. Check if .env file exists in project root")
        print("2. Verify .env file format:")
        print("   MOBILE_NUMBER=your_mobile_number")
        print("   UCC=your_ucc")
        print("   TOTP=your_totp")
        print("   MPIN=your_mpin")
        print("3. Ensure no spaces around = sign")
        print("4. Ensure no quotes around values")
        return None
    
    totp_client = KotakTOTPClient()
    login_data = await totp_client.login_with_totp(access_token, mobile_number, ucc, totp)

    if not login_data:
        print("❌ TOTP authentication failed")
        return None

    print(f"✅ TOTP authentication successful")
    print(f"SID: {login_data['data']['sid']}")
    print(f"JWT Token: {login_data['data']['token'][:20]}...")

    ## STEP 3: Final session validation with MPIN
    print("🔒 Step 3: Final session validation...")
    sid = login_data["data"]["sid"]
    jwt_auth_token = login_data["data"]["token"]
    # mpin = os.getenv("MPIN")
    
    if not mpin:
        print("❌ Missing MPIN environment variable")
        return None
    
    final_client = KotakFinalSessionClient()
    session_data = await final_client.validate_final_session(access_token, sid, jwt_auth_token, mpin)
    
    if not session_data:
        print("❌ Final session validation failed")
        return None

    print("✅ Final session validation successful!")
    print(f"Final SID: {session_data['data']['sid']}")
    print(f"Final Token: {session_data['data']['token'][:20]}...")
    
    ## STEP 4: Save session for future use
    print("💾 Step 4: Saving session for future use...")
    save_success = await session_manager.save_session(session_data)
    
    if save_success:
        print("✅ Session saved successfully! Will be reused for future calls.")
        
        # Display session info
        session_info = session_manager.get_session_info()
        if session_info:
            print(f"📊 Session expires at: {session_info['expires_at']}")
    else:
        print("⚠️ Failed to save session, but authentication completed successfully")
    
    print("\n🎉 Authentication completed successfully!")
    print("🔐 You can now make authenticated API calls using the session manager")
    
    return session_data




# if __name__ == "__main__":
#     asyncio.run(main())