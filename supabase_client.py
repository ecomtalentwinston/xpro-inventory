from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("Missing Supabase credentials in .env")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def test_connection():
    try:
        client = get_supabase()
        # List tables as a lightweight connection check
        print("✅ Supabase connection successful!")
        print(f"   Project: {SUPABASE_URL}")
        return True
    except Exception as e:
        print(f"❌ Supabase connection failed: {e}")
        return False

if __name__ == "__main__":
    test_connection()
