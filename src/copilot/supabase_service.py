import os
import json
import requests
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

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE_FILE = os.path.join(BASE_DIR, "config", "reports_cache.json")

def _load_disk_cache() -> List[Dict[str, Any]]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            print(f"[!] Warning loading local reports cache from disk: {e}")
    return []

def _save_disk_cache(cache_list: List[Dict[str, Any]]):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_list, f, indent=2, default=str)
    except Exception as e:
        print(f"[!] Warning saving local reports cache to disk: {e}")

_LOCAL_REPORTS_CACHE: List[Dict[str, Any]] = _load_disk_cache()

def _query_supabase_rest(service: Optional[str] = None, limit: int = 50) -> Optional[List[Dict[str, Any]]]:
    if not SUPABASE_URL or not SUPABASE_KEY or SUPABASE_URL == "your_supabase_url_here":
        return None
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?select=*&order=closed_at.desc&limit={limit}"
        if service:
            url += f"&service=eq.{service}"
        res = requests.get(url, headers=headers, timeout=5.0)
        if res.status_code == 200:
            return res.json()
        else:
            print(f"[!] Supabase REST GET error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[!] Supabase REST GET exception: {e}")
    return None

def _upsert_supabase_rest(record: Dict[str, Any]) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY or SUPABASE_URL == "your_supabase_url_here":
        return False
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
        res = requests.post(url, json=record, headers=headers, timeout=5.0)
        if res.status_code in (200, 201, 204):
            return True
        else:
            print(f"[!] Supabase REST POST error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[!] Supabase REST POST exception: {e}")
    return False

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
    Stores an incident post-mortem report in Supabase (via REST API) with disk persistence fallback.
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
        "created_at": (created_at.isoformat() if isinstance(created_at, datetime) else str(created_at) if created_at else now_iso),
        "closed_at": now_iso
    }

    persisted = _upsert_supabase_rest(report_record)
    if persisted:
        print(f"[*] Successfully saved post-mortem report for {ticket_id} in Supabase table '{SUPABASE_TABLE}'")
    else:
        print(f"[!] Supabase write fallback triggered. Preserving report in local disk cache.")

    report_record["persisted_to_supabase"] = persisted
    
    # Update local memory cache and sync to disk
    existing_idx = next((i for i, r in enumerate(_LOCAL_REPORTS_CACHE) if r.get("ticket_id") == ticket_id), None)
    if existing_idx is not None:
        _LOCAL_REPORTS_CACHE[existing_idx] = report_record
    else:
        _LOCAL_REPORTS_CACHE.append(report_record)
    
    _save_disk_cache(_LOCAL_REPORTS_CACHE)
    return report_record

def get_past_reports(limit: int = 50, service: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetches past incident reports from Supabase (REST API) or persistent disk cache.
    """
    supabase_data = _query_supabase_rest(service=service, limit=limit)
    if supabase_data is not None and len(supabase_data) > 0:
        # Sync remote data into local cache
        for remote_rec in supabase_data:
            tid = remote_rec.get("ticket_id")
            if tid and not any(r.get("ticket_id") == tid for r in _LOCAL_REPORTS_CACHE):
                _LOCAL_REPORTS_CACHE.append(remote_rec)
        _save_disk_cache(_LOCAL_REPORTS_CACHE)
        return supabase_data

    # Fallback to local disk cache
    results = _LOCAL_REPORTS_CACHE
    if service:
        results = [r for r in results if r.get("service") == service]
    return list(reversed(results))[:limit]
