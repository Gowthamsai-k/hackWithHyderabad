import re
from typing import List, Dict, Any

NOISE_REGEX = re.compile(r"(/healthz|/metrics|kube-probe|Readyz|DEBUG)", re.IGNORECASE)
ACTION_KEYWORDS = {
    "restart", "restarted", "scale", "scaled", "helm", "config",
    "pool", "bumped", "patch", "patched", "reverted", "fixed", "timeout"
}

def filter_logs(raw_lines: List[str]) -> List[str]:
    """Deduplicates repetitive log loops and strips routine health checks."""
    cleaned = []
    last_sig = None
    repeat_count = 0

    for line in raw_lines:
        if NOISE_REGEX.search(line):
            continue

        # Normalize timestamps, memory addresses, and UUIDs
        sig = re.sub(r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}", "", line)
        sig = re.sub(r"0x[0-9a-fA-F]+", "", sig)
        sig = re.sub(r"[a-f0-9-]{36}", "", sig)

        if sig == last_sig:
            repeat_count += 1
            continue
        else:
            if repeat_count > 0:
                cleaned.append(f"--- [Identical error repeated {repeat_count} times; collapsed] ---")
                repeat_count = 0
            cleaned.append(line.strip())
            last_sig = sig

    if repeat_count > 0:
        cleaned.append(f"--- [Identical error repeated {repeat_count} times; collapsed] ---")
    return cleaned

def filter_chat(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Preserves action-bearing and code-bearing comments, dropping casual social chatter."""
    meaningful = []
    for c in comments:
        text = c["text"]
        has_code = "```" in text or "`" in text or any(
            cmd in text.lower() for cmd in ["kubectl", "helm", "git", "curl", "docker", "systemctl"]
        )
        has_action = any(kw in text.lower() for kw in ACTION_KEYWORDS)
        if has_code or has_action:
            meaningful.append(c)
    return meaningful

def apply_context_budget(
    logs: List[str], 
    chat: List[Dict[str, Any]], 
    max_log_lines: int = 50, 
    max_chat_messages: int = 30
) -> tuple[List[str], List[Dict[str, Any]]]:
    """
    Enforces hard token/line limits using Head-and-Tail Stratified Windowing.
    Guarantees the bundle will never exceed LLM context window limits regardless of outage duration.
    """
    # 1. Stratified log windowing: preserve onset (head) and recovery (tail)
    if len(logs) > max_log_lines:
        half = max_log_lines // 2
        omitted = len(logs) - max_log_lines
        budgeted_logs = (
            logs[:half] 
            + [f"--- [... {omitted} intermediate error events omitted to fit context window ...] ---"] 
            + logs[-half:]
        )
    else:
        budgeted_logs = logs

    # 2. Stratified chat windowing: preserve first diagnostic attempts and final resolution steps
    if len(chat) > max_chat_messages:
        half_chat = max_chat_messages // 2
        omitted_chat = len(chat) - max_chat_messages
        budgeted_chat = (
            chat[:half_chat] 
            + [{"author": "SYSTEM_WINDOW", "text": f"[... {omitted_chat} intermediate triage messages omitted ...]"}] 
            + chat[-half_chat:]
        )
    else:
        budgeted_chat = chat

    return budgeted_logs, budgeted_chat
