import os
import sys
import getpass
import hashlib
import secrets

def hash_password(password: str) -> str:
    """Create a pbkdf2_hmac password hash (format: salt:hash)"""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{key.hex()}"

def main():
    print("🚀 Setting up Supabase Users (admin & user)")
    
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    
    if not url or not key:
        print("❌ Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are missing.")
        print("Please run this script with your environment variables set:")
        print("SUPABASE_URL='...' SUPABASE_SERVICE_ROLE_KEY='...' python3 setup_users.py")
        sys.exit(1)
        
    try:
        from app.supabase_client import get_supabase
        client = get_supabase()
        print("✅ Connected to Supabase!")
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        sys.exit(1)
        
    print("\nConfigure 'admin' user:")
    admin_pass = getpass.getpass("Enter password for 'admin': ")
    admin_confirm = getpass.getpass("Confirm password for 'admin': ")
    if admin_pass != admin_confirm:
        print("❌ Passwords do not match!")
        sys.exit(1)
        
    print("\nConfigure 'user' user:")
    user_pass = getpass.getpass("Enter password for 'user': ")
    user_confirm = getpass.getpass("Confirm password for 'user': ")
    if user_pass != user_confirm:
        print("❌ Passwords do not match!")
        sys.exit(1)
        
    users_to_add = [
        {"username": "admin", "pwd_hash": hash_password(admin_pass), "role": "admin"},
        {"username": "user",  "pwd_hash": hash_password(user_pass),  "role": "preparer"}
    ]
    
    print("\nUpserting users into 'digihub_users' table...")
    for u in users_to_add:
        try:
            # Check if user exists first
            existing = client.table("digihub_users").select("*").eq("username", u["username"]).execute()
            if existing.data:
                # Update existing user
                client.table("digihub_users").update({"pwd_hash": u["pwd_hash"], "role": u["role"]}).eq("username", u["username"]).execute()
                print(f"✅ Updated existing user: {u['username']}")
            else:
                # Insert new user
                client.table("digihub_users").insert(u).execute()
                print(f"✅ Created new user: {u['username']}")
        except Exception as e:
            print(f"❌ Error adding user '{u['username']}': {e}")
            print("Did you run the 'supabase_migration.sql' in your Supabase SQL Editor?")
            sys.exit(1)
            
    print("\n🎉 Setup complete! You can now log into your Vercel app.")

if __name__ == "__main__":
    main()
