import re
import time
import hashlib
from collections import deque
from typing import Optional, List, Dict, Callable

CRASH_REGEX = re.compile(
    r"(ERROR|FATAL|CRITICAL|Exception|ConnectionPool timeout|ConnectionTimeout|OOMKilled|504 Gateway Timeout|IndexOutOfBoundsException|ArrayIndexOutOfBoundsException|NullPointerException)",
    re.IGNORECASE
)

class BackgroundLogWatcher:
    """
    Passive In-Memory Ring Buffer Listener with regex crash detection
    and fingerprint debouncing.
    """
    def __init__(self, buffer_size: int = 100, debounce_window_sec: float = 30.0):
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
