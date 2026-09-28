import os
import sys
import json
import re
import platform
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union
from dotenv import load_dotenv
from hindsight_client import Hindsight
from .schemas import SystemEnvironmentMetadata

load_dotenv()

def get_env_var(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'\"")
    return val

HINDSIGHT_URL = get_env_var("HINDSIGHT_BASE_URL", "http://localhost:8888")
HINDSIGHT_API_KEY = get_env_var("HINDSIGHT_API_KEY", "")
BANK_ID = get_env_var("BANK_ID", "incident-ops-bank")

client = Hindsight(base_url=HINDSIGHT_URL, api_key=HINDSIGHT_API_KEY)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HINDSIGHT_CACHE_FILE = os.path.join(BASE_DIR, "config", "hindsight_fallback.json")

def _load_hindsight_disk_cache() -> List[Dict[str, Any]]:
    if os.path.exists(HINDSIGHT_CACHE_FILE):
        try:
            with open(HINDSIGHT_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            print(f"[!] Warning loading Hindsight fallback memory from disk: {e}")
    return []

def _save_hindsight_disk_cache(cache_list: List[Dict[str, Any]]):
    try:
        os.makedirs(os.path.dirname(HINDSIGHT_CACHE_FILE), exist_ok=True)
        with open(HINDSIGHT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_list, f, indent=2, default=str)
    except Exception as e:
        print(f"[!] Warning saving Hindsight fallback memory to disk: {e}")

_FALLBACK_MEMORY_STORE: List[Dict[str, Any]] = _load_hindsight_disk_cache()

def get_system_metadata() -> Dict[str, Any]:
    """Dynamically gathers system architecture, Python version, and OS info."""
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "processor": platform.processor() or "unknown",
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    }

def init_bank(bank_id: Optional[str] = None):
    """Ensures the Hindsight memory bank exists with appropriate cognitive settings."""
    target_bank = bank_id or get_env_var("BANK_ID", "incident-ops-bank")
    try:
        client.create_bank(
            bank_id=target_bank,
            name="Incident SRE Brain",
            mission="Retain incident post-mortems, verified runbooks, failed attempts, and anti-pattern warnings.",
            disposition={"skepticism": 2, "literalism": 4, "empathy": 1}
        )
        print(f"[*] Initialized Hindsight bank: {target_bank}")
    except Exception as e:
        print(f"[*] Hindsight bank init notice for '{target_bank}': {e}")

def _parse_item_timestamp(item: Dict[str, Any]) -> datetime:
    ts = item.get("closed_at") or item.get("timestamp")
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    elif isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)

def format_runbook_memory_text(raw_text: str) -> str:
    """Formats raw Hindsight post-mortem text into clean structured bullet points."""
    if not raw_text or not raw_text.strip():
        return raw_text

    inc_m = re.search(r"Incident\s+\[(.*?)\]\s+on\s+'(.*?)'", raw_text)
    ticket_ref = inc_m.group(1) if inc_m else None
    service_ref = inc_m.group(2) if inc_m else None

    runtime_m = re.search(r"Runtime:\s*(.*?)\.\s*Dependencies:", raw_text)
    runtime = runtime_m.group(1) if runtime_m else None

    git_m = re.search(r"Git:\s*(.*?)\.\s*Root Cause:", raw_text)
    git = git_m.group(1) if git_m else None

    cause_m = re.search(r"Root Cause:\s*(.*?)\.\.?\s*Verified Fix:", raw_text)
    root_cause = cause_m.group(1) if cause_m else None

    fix_m = re.search(r"Verified Fix:\s*(.*?)\.\.?\s*(?:Failed Attempts:|Anti-Pattern Warning:)", raw_text)
    verified_fix = fix_m.group(1) if fix_m else None

    anti_m = re.search(r"Anti-Pattern Warning:\s*(.*)", raw_text)
    anti_warning = anti_m.group(1).strip() if anti_m else None

    lines = []
    if ticket_ref and service_ref:
        lines.append(f"📌 **Incident Reference:** `{ticket_ref}` (`{service_ref}`)")
    if runtime or git:
        lines.append(f"⚙️ **Environment Metadata:** Runtime `{runtime or 'unknown'}` | Git `{git or 'HEAD'}`")
    if root_cause:
        lines.append(f"🔍 **Root Cause:** {root_cause.strip()}")
    if verified_fix:
        lines.append(f"✅ **Verified Fix:** {verified_fix.strip()}")
    if anti_warning:
        lines.append(f"⚠️ **Anti-Pattern Warning:** {anti_warning.strip()}")

    if lines:
        return "\n".join([f"• {l}" for l in lines])
    return raw_text

def recall_memory(
    service: str, 
    error_type: str, 
    bank_id: Optional[str] = None,
    dependency: Optional[str] = None
) -> Optional[str]:
    """Queries Hindsight using multi-arm retrieval, prioritizing the most recent incident resolutions."""
    target_bank = bank_id or get_env_var("BANK_ID", "incident-ops-bank")
    
    query_str = f"Past fixes, root causes, architecture changes, and failed attempts for {service} encountering {error_type}"
    if dependency:
        query_str += f" with dependency {dependency}"

    # 1. Attempt live Hindsight recall
    try:
        memories = client.recall(
            bank_id=target_bank,
            query=query_str,
            budget="high"
        )
        if memories and memories.results:
            matching_results = []
            for r in memories.results:
                if not r.text:
                    continue
                r_meta = getattr(r, "metadata", {}) or {}
                r_service = r_meta.get("service") if isinstance(r_meta, dict) else None
                if r_service:
                    if r_service.lower() == service.lower():
                        matching_results.append(format_runbook_memory_text(r.text))
                else:
                    text_lower = r.text.lower()
                    svc_lower = service.lower()
                    if f"'{svc_lower}'" in text_lower or f"on '{svc_lower}'" in text_lower or f"service '{svc_lower}'" in text_lower:
                        matching_results.append(format_runbook_memory_text(r.text))

            if matching_results:
                return "\n\n".join(matching_results[:3])
    except Exception as e:
        print(f"[!] Hindsight live recall failed: {e}")

    # 2. Check fallback memory store (sorted descending by timestamp to prioritize latest incident fixes)
    fallback_matches = [
        item for item in _FALLBACK_MEMORY_STORE
        if item.get("service") == service
    ]
    if fallback_matches:
        sorted_matches = sorted(fallback_matches, key=_parse_item_timestamp, reverse=True)
        return "\n\n".join([format_runbook_memory_text(m['content']) for m in sorted_matches[:3]])

    return None

def get_latest_memory_for_service(service: str) -> Optional[Dict[str, Any]]:
    """Returns the most recent retained post-mortem item for a service."""
    fallback_matches = [
        item for item in _FALLBACK_MEMORY_STORE
        if item.get("service") == service
    ]
    if not fallback_matches:
        return None
    sorted_matches = sorted(fallback_matches, key=_parse_item_timestamp, reverse=True)
    return sorted_matches[0]


def retain_post_mortem(
    ticket_id: str, 
    service: str, 
    post_mortem, 
    closed_at: datetime,
    bank_id: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    system_env: Optional[Union[SystemEnvironmentMetadata, Dict[str, Any]]] = None
):
    """
    Retains structured incident resolutions, causal links, and rich environment metadata into Hindsight.
    Binds environment context (runtime, dependencies, git commit) per section 4 of Prompt.md.
    """
    target_bank = bank_id or get_env_var("BANK_ID", "incident-ops-bank")
    
    if isinstance(system_env, SystemEnvironmentMetadata):
        runtime_info = system_env.runtime
        dep_summary = json.dumps(system_env.dependencies)
        git_commit = system_env.git_commit or "HEAD"
        deps_dict = system_env.dependencies
    elif isinstance(system_env, dict):
        runtime_info = system_env.get("runtime", system_env.get("python_version", "unknown"))
        deps_dict = system_env.get("dependencies", {})
        dep_summary = json.dumps(deps_dict) if isinstance(deps_dict, dict) else str(deps_dict)
        git_commit = system_env.get("git_commit", "HEAD")
    else:
        sys_meta = get_system_metadata()
        runtime_info = sys_meta.get("python_version", "unknown")
        deps_dict = {}
        dep_summary = "{}"
        git_commit = "HEAD"

    content = (
        f"Incident [{ticket_id}] on '{service}'. "
        f"Runtime: {runtime_info}. Dependencies: {dep_summary}. Git: {git_commit}. "
        f"Root Cause: {post_mortem.root_cause}. "
        f"Verified Fix: {post_mortem.verified_fix}. "
        f"Failed Attempts: {'; '.join(post_mortem.failed_attempts)}. "
        f"Anti-Pattern Warning: {post_mortem.anti_pattern_warning}"
    )

    metadata_payload = {
        "ticket_id": str(ticket_id),
        "service": str(service),
        "git_commit": str(git_commit),
        "runtime": str(runtime_info),
        "type": "verified_post_mortem"
    }

    if deps_dict and isinstance(deps_dict, dict):
        for k, v in deps_dict.items():
            metadata_payload[f"dep_{k}"] = str(v)

    if extra_metadata:
        for k, v in extra_metadata.items():
            metadata_payload[str(k)] = str(v)

    retained_live = False
    try:
        client.retain(
            bank_id=target_bank,
            content=content,
            context=f"service:{service}:incidents",
            timestamp=closed_at,
            metadata=metadata_payload,
            retain_async=False
        )
        retained_live = True
        print(f"[*] Successfully retained post-mortem for {ticket_id} in Hindsight bank: {target_bank}")
    except Exception as e:
        print(f"[!] Hindsight live retain failed: {e}")

    # Always keep in local fallback store as well
    _FALLBACK_MEMORY_STORE.append({
        "ticket_id": ticket_id,
        "service": service,
        "content": content,
        "closed_at": (closed_at.isoformat() if isinstance(closed_at, datetime) else str(closed_at)),
        "metadata": metadata_payload,
        "retained_live": retained_live
    })
    _save_hindsight_disk_cache(_FALLBACK_MEMORY_STORE)
    print(f"[*] Recorded post-mortem in knowledge store for ticket {ticket_id}")

def get_all_memories() -> List[Dict[str, Any]]:
    return list(_FALLBACK_MEMORY_STORE)

def reset_memory_bank():
    global _FALLBACK_MEMORY_STORE
    _FALLBACK_MEMORY_STORE.clear()
    if os.path.exists(HINDSIGHT_CACHE_FILE):
        try:
            os.remove(HINDSIGHT_CACHE_FILE)
        except Exception:
            pass
    print("[*] Memory bank cleared.")
