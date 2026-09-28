import re
import os
import time
import hashlib
from collections import deque
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

def get_env_var(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'\"")
    return val

DEFAULT_REGEX_STR = (
    r"(ERROR|FATAL|CRITICAL|Exception|ConnectionPool timeout|ConnectionTimeout|"
    r"OOMKilled|504 Gateway Timeout|IndexOutOfBoundsException|ArrayIndexOutOfBoundsException|"
    r"NullPointerException|Panic|Traceback)"
)
CUSTOM_REGEX = get_env_var("CRASH_REGEX_PATTERN", DEFAULT_REGEX_STR)
CRASH_REGEX = re.compile(CUSTOM_REGEX, re.IGNORECASE)

BUFFER_SIZE = int(get_env_var("LOG_BUFFER_SIZE", "100"))
DEBOUNCE_WINDOW_SEC = float(get_env_var("DEBOUNCE_WINDOW_SEC", "30.0"))

class BackgroundLogWatcher:
    """
    Passive In-Memory Ring Buffer Listener with regex crash detection
    and fingerprint debouncing.
    """
    def __init__(self, buffer_size: int = BUFFER_SIZE, debounce_window_sec: float = DEBOUNCE_WINDOW_SEC):
        self.ring_buffer: deque = deque(maxlen=buffer_size)
        self.debounce_window_sec = debounce_window_sec
        self.recent_fingerprints: Dict[str, float] = {}

    def push_line(self, line: str, service: str = "checkout-service") -> Optional[str]:
        """
        Appends a line to the ring buffer.
        Returns error signature string if a new debounced crash is detected, else None.
        """
        timestamped_line = line.strip()
        self.ring_buffer.append(timestamped_line)

        # Evaluate against crash patterns
        match = CRASH_REGEX.search(timestamped_line)
        if not match:
            return None

        error_type = match.group(0)
        # Compute debouncing fingerprint
        fingerprint_raw = f"{service}:{error_type}"
        fingerprint = hashlib.md5(fingerprint_raw.encode("utf-8")).hexdigest()

        now = time.time()
        last_seen = self.recent_fingerprints.get(fingerprint, 0)
        if now - last_seen < self.debounce_window_sec:
            # Debounced: Suppress duplicate trigger during active storm
            return None

        # Record trigger timestamp
        self.recent_fingerprints[fingerprint] = now
        return error_type

    def get_context_slice(self, count: int = 50) -> List[str]:
        """Returns the most recent N lines leading up to and including the crash."""
        return list(self.ring_buffer)[-count:]

    def clear(self):
        self.ring_buffer.clear()
        self.recent_fingerprints.clear()
