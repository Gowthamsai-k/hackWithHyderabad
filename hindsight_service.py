import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from hindsight_client import Hindsight

load_dotenv()

HINDSIGHT_URL = os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888")
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "")
BANK_ID = os.getenv("BANK_ID", "incident-ops-bank")

client = Hindsight(base_url=HINDSIGHT_URL, api_key=HINDSIGHT_API_KEY)

# In-memory fallback repository in case external Hindsight server is unavailable/unconfigured
_FALLBACK_MEMORY_STORE: List[Dict[str, Any]] = []

def init_bank():
    """Ensures the Hindsight memory bank exists with appropriate cognitive settings."""
    try:
        client.create_bank(
            bank_id=BANK_ID,
            name="Incident SRE Brain",
            mission="Retain incident post-mortems, verified runbooks, failed attempts, and anti-pattern warnings.",
            disposition={"skepticism": 2, "literalism": 4, "empathy": 1}
        )
        print(f"[*] Initialized Hindsight bank: {BANK_ID}")
    except Exception as e:
        print(f"[*] Hindsight bank init notice (fallback enabled if offline): {e}")

def recall_memory(service: str, error_type: str) -> Optional[str]:
    """Queries Hindsight using multi-arm retrieval (Semantic + BM25 + Graph)."""
    # 1. Attempt live Hindsight recall
    try:
        memories = client.recall(
            bank_id=BANK_ID,
            query=f"Past fixes, root causes, and failed attempts for {service} encountering {error_type}",
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

def retain_post_mortem(ticket_id: str, service: str, post_mortem, closed_at: datetime):
    """Retains structured incident resolutions and causal links into Hindsight."""
    content = (
        f"Incident [{ticket_id}] on service '{service}'. "
        f"Root Cause: {post_mortem.root_cause}. "
        f"Verified Fix: {post_mortem.verified_fix}. "
        f"Failed Attempts: {'; '.join(post_mortem.failed_attempts)}. "
        f"Anti-Pattern Warning: {post_mortem.anti_pattern_warning}"
    )

    retained_live = False
    try:
        client.retain(
            bank_id=BANK_ID,
            content=content,
            context=f"service:{service}:incidents",
            timestamp=closed_at,
            metadata={"ticket_id": str(ticket_id), "service": str(service), "type": "verified_post_mortem"},
            retain_async=False
        )
        retained_live = True
        print(f"[*] Successfully retained post-mortem for {ticket_id} in Hindsight bank: {BANK_ID}")
    except Exception as e:
        print(f"[!] Hindsight live retain failed: {e}")

    # Always keep in local fallback store as well
    _FALLBACK_MEMORY_STORE.append({
        "ticket_id": ticket_id,
        "service": service,
        "content": content,
        "closed_at": closed_at,
        "retained_live": retained_live
    })
    print(f"[*] Recorded post-mortem in knowledge store for ticket {ticket_id}")

def get_all_memories() -> List[Dict[str, Any]]:
    return list(_FALLBACK_MEMORY_STORE)

def reset_memory_bank():
    global _FALLBACK_MEMORY_STORE
    _FALLBACK_MEMORY_STORE.clear()
    print("[*] Memory bank cleared.")
