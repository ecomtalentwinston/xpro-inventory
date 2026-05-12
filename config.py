import os
from dotenv import load_dotenv

load_dotenv()

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Amazon SP-API
AMAZON_CLIENT_ID = os.getenv("AMAZON_CLIENT_ID")
AMAZON_CLIENT_SECRET = os.getenv("AMAZON_CLIENT_SECRET")
AMAZON_APP_ID = os.getenv("AMAZON_APP_ID")
AMAZON_REFRESH_TOKEN = os.getenv("AMAZON_REFRESH_TOKEN")
AMAZON_MARKETPLACE_ID = os.getenv("AMAZON_MARKETPLACE_ID", "ATVPDKIKX0DER")
AMAZON_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
AMAZON_API_BASE = "https://sellingpartnerapi-na.amazon.com"
