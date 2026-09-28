import os
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

def get_env_var(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'\"")
    return val

SUPABASE_URL = get_env_var("SUPABASE_URL", "")
SUPABASE_KEY = get_env_var("SUPABASE_KEY", "") or get_env_var("SUPABASE_SERVICE_ROLE_KEY", "") or get_env_var("SUPABASE_ANON_KEY", "")
SUPABASE_TABLE = get_env_var("SUPABASE_TABLE", "incident_reports")

supabase_client = None

if SUPABASE_URL and SUPABASE_KEY and SUPABASE_URL != "your_supabase_url_here":
    try:
        from supabase import create_client, Client
        supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print(f"[*] Supabase client initialized for table '{SUPABASE_TABLE}'")
    except Exception as e:
        print(f"[!] Supabase initialization warning: {e}")

# In-memory storage cache for reports so endpoints work immediately even before Supabase credentials are plugged in
_LOCAL_REPORTS_CACHE: List[Dict[str, Any]] = []

def store_incident_report(
    ticket_id: str,
    service: str,
    title: str,
    root_cause: str,
    verified_fix: str,
    anti_pattern: str,
    failed_attempts: List[str],
    environment_metadata: Optional[Dict[str, Any]] = None,
    raw_logs: Optional[List[str]] = None,
    created_at: Optional[datetime] = None,
    closed_at: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Stores an incident post-mortem report in Supabase with automatic fallback to local store.
    """
    now_iso = (closed_at or datetime.now(timezone.utc)).isoformat()
    
    report_record = {
        "ticket_id": ticket_id,
        "service": service,
        "title": title,
        "root_cause": root_cause,
        "verified_fix": verified_fix,
        "anti_pattern": anti_pattern,
        "failed_attempts": failed_attempts,
        "environment_metadata": environment_metadata or {},
        "raw_logs_sample": (raw_logs[:10] if raw_logs else []),
        "created_at": (created_at.isoformat() if created_at else now_iso),
        "closed_at": now_iso
    }

    persisted_to_supabase = False

    if supabase_client:
        try:
            # Upsert into Supabase table
            res = supabase_client.table(SUPABASE_TABLE).upsert(report_record).execute()
            persisted_to_supabase = True
            print(f"[*] Successfully saved post-mortem report for {ticket_id} in Supabase table '{SUPABASE_TABLE}'")
        except Exception as e:
            print(f"[!] Supabase write failed: {e}. Report preserved in local fallback cache.")

    report_record["persisted_to_supabase"] = persisted_to_supabase
    _LOCAL_REPORTS_CACHE.append(report_record)
    return report_record

def get_past_reports(limit: int = 50, service: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetches past incident reports from Supabase or fallback cache.
    """
    if supabase_client:
        try:
            query = supabase_client.table(SUPABASE_TABLE).select("*").order("closed_at", desc=True).limit(limit)
            if service:
                query = query.eq("service", service)
            res = query.execute()
            if res.data:
                return res.data
        except Exception as e:
            print(f"[!] Supabase query failed: {e}. Reading from local fallback cache.")

    # Return from memory cache
    results = _LOCAL_REPORTS_CACHE
    if service:
        results = [r for r in results if r.get("service") == service]
    return list(reversed(results))[:limit]
