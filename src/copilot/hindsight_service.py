import os
import sys
import platform
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from hindsight_client import Hindsight

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

# In-memory fallback repository in case external Hindsight server is unavailable/unconfigured
_FALLBACK_MEMORY_STORE: List[Dict[str, Any]] = []

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

def recall_memory(service: str, error_type: str, bank_id: Optional[str] = None) -> Optional[str]:
    """Queries Hindsight using multi-arm retrieval (Semantic + BM25 + Graph)."""
    target_bank = bank_id or get_env_var("BANK_ID", "incident-ops-bank")
    
    # 1. Attempt live Hindsight recall
    try:
        memories = client.recall(
            bank_id=target_bank,
            query=f"Past fixes, root causes, architecture changes, and failed attempts for {service} encountering {error_type}",
            budget="high"
        )
        if memories and memories.results:
            results_text = [f"- {r.text}" for r in memories.results[:3] if r.text]
            if results_text:
                return "\n".join(results_text)
    except Exception as e:
        print(f"[!] Hindsight live recall failed: {e}")

    # 2. Check fallback memory store
    fallback_matches = [
        item["content"] for item in _FALLBACK_MEMORY_STORE
        if item.get("service") == service or service.lower() in item.get("content", "").lower()
    ]
    if fallback_matches:
        return "\n".join([f"- {m}" for m in fallback_matches[:3]])

    return None

def retain_post_mortem(
    ticket_id: str, 
    service: str, 
    post_mortem, 
    closed_at: datetime,
    bank_id: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None
):
    """Retains structured incident resolutions, causal links, and rich environment metadata into Hindsight."""
    target_bank = bank_id or get_env_var("BANK_ID", "incident-ops-bank")
    
    # Enrich content with environment metadata
    sys_meta = get_system_metadata()
    if extra_metadata:
        sys_meta.update(extra_metadata)

    content = (
        f"Incident [{ticket_id}] on service '{service}'. "
        f"System Env: OS={sys_meta.get('os')} ({sys_meta.get('architecture')}), Runtime={sys_meta.get('python_version')}. "
        f"Root Cause: {post_mortem.root_cause}. "
        f"Verified Fix: {post_mortem.verified_fix}. "
        f"Failed Attempts: {'; '.join(post_mortem.failed_attempts)}. "
        f"Anti-Pattern Warning: {post_mortem.anti_pattern_warning}"
    )

    retained_live = False
    meta_payload = {
        "ticket_id": str(ticket_id),
        "service": str(service),
        "type": "verified_post_mortem",
        "system_os": str(sys_meta.get("os")),
        "architecture": str(sys_meta.get("architecture")),
        "runtime": str(sys_meta.get("python_version"))
    }
    if extra_metadata:
        for k, v in extra_metadata.items():
            meta_payload[k] = str(v)

    try:
        client.retain(
            bank_id=target_bank,
            content=content,
            context=f"service:{service}:incidents",
            timestamp=closed_at,
            metadata=meta_payload,
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
        "closed_at": closed_at,
        "metadata": meta_payload,
        "retained_live": retained_live
    })
    print(f"[*] Recorded post-mortem in knowledge store for ticket {ticket_id}")

def get_all_memories() -> List[Dict[str, Any]]:
    return list(_FALLBACK_MEMORY_STORE)

def reset_memory_bank():
    global _FALLBACK_MEMORY_STORE
    _FALLBACK_MEMORY_STORE.clear()
    print("[*] Memory bank cleared.")
