from supabase import create_client, Client 
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_TOKEN")
supabase: Client = create_client(url, key)

# Define initial tokens
access_token = os.getenv("SC_ACCESS_TOKEN ")
refresh_token = os.getenv("SC_REFRESH_TOKEN ")
expires_in = 3600  
expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

# Insert into Supabase
data = {
    "service": "soundcloud",
    "access_token": access_token,
    "refresh_token": refresh_token,
    "expires_at": expires_at.isoformat()
}

response = supabase.table("oauth_tokens").insert(data).execute()

print("Inserted:", response)
