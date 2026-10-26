import os
import sys

def test_supabase_connection():
    print("Testing Supabase Connection...")
    
    # Check if env vars are present
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    
    if not url or not key:
        print("❌ Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are not set.")
        print("   Please run this script with your environment variables, e.g.:")
        print("   SUPABASE_URL='https://...' SUPABASE_SERVICE_ROLE_KEY='...' python test_supabase.py")
        sys.exit(1)
        
    try:
        from app.supabase_client import get_supabase
        client = get_supabase()
        print("✅ Supabase client initialized successfully.")
    except Exception as e:
        print(f"❌ Failed to initialize Supabase client: {e}")
        sys.exit(1)
        
    print("\nTesting 'digihub_users' table access...")
    try:
        result = client.table("digihub_users").select("*").execute()
        users = result.data
        print(f"✅ Successfully accessed 'digihub_users' table.")
        print(f"   Found {len(users)} user(s).")
        
        for u in users:
            print(f"   - Username: {u.get('username')}, Role: {u.get('role')}")
            
        if any(u.get('username') == 'admin' for u in users):
            print("✅ Admin user is present and authorized to access the app.")
        else:
            print("⚠️ Admin user not found. Please add the admin user to the 'digihub_users' table.")
            
    except Exception as e:
        print(f"❌ Failed to query 'digihub_users' table. Have you run the SQL migration? Error: {e}")
        sys.exit(1)
        
    print("\n✨ All tests passed! Supabase is connected and users are set up.")

if __name__ == "__main__":
    test_supabase_connection()
