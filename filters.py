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
