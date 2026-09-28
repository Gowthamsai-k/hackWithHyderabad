import os
import requests
from dotenv import load_dotenv

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL", "").strip("'\"")
supabase_key = os.getenv("SUPABASE_KEY", "").strip("'\"")
supabase_table = os.getenv("SUPABASE_TABLE", "incident_reports").strip("'\"")

print("--- Testing Supabase REST API with Requests ---")
headers = {
    "apikey": supabase_key,
    "Authorization": f"Bearer {supabase_key}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

rest_endpoint = f"{supabase_url}/rest/v1/{supabase_table}"
print("Endpoint:", rest_endpoint)

try:
    r = requests.get(f"{rest_endpoint}?select=*&limit=5", headers=headers, timeout=5.0)
    print("HTTP Status:", r.status_code)
    print("HTTP Response:", r.text)
except Exception as e:
    print("REST Error:", e)
