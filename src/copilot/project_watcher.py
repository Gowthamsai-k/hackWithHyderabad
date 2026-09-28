import time
import os
import re
import yaml
import requests
import threading

COPILOT_TRIGGER_URL = os.getenv("COPILOT_TRIGGER_URL", "http://127.0.0.1:8000/api/v1/alerts/trigger")
CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "projects.yaml"))

DEFAULT_ERROR_PATTERNS = [
    "Exception", "Error", "Traceback", "Fatal", "Panic", 
    "IndexOutOfBoundsException", "ArrayIndexOutOfBoundsException",
    "NullPointerException", "ConnectionPool timeout", "OOMKilled"
]

_ACTIVE_WATCHER_THREADS = {}
_ACTIVE_WATCHER_STOP_FLAGS = {}
_LOCK = threading.Lock()

def extract_exception_name(line: str) -> str:
    matches = re.findall(r"([a-zA-Z0-9_\.]*(?:Exception|Error|Fatal|Panic))(?::|\s|$)", line)
    if matches:
        specific = [m for m in matches if m not in ("Exception", "Error")]
        chosen = specific[-1] if specific else matches[-1]
        return chosen.split(".")[-1]
    if ":" in line:
        return line.split(":")[0].strip()
    return "ApplicationCrash"

def load_projects_config():
    if not os.path.exists(CONFIG_PATH):
        return []
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("projects", [])
    except Exception as e:
        print(f"[!] Error reading {CONFIG_PATH}: {e}")
        return []

def tail_project_log(project: dict, stop_flag: threading.Event):
    log_file = project.get("log_file")
    service = project.get("service") or project.get("id", "unknown-service")
    raw_patterns = project.get("error_patterns") or DEFAULT_ERROR_PATTERNS
    error_patterns = [re.compile(p, re.IGNORECASE) for p in raw_patterns]

    # Resolve log path
    if not os.path.isabs(log_file):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        log_file_abs = os.path.abspath(os.path.join(base_dir, log_file))
    else:
        log_file_abs = log_file

    os.makedirs(os.path.dirname(log_file_abs) if os.path.dirname(log_file_abs) else ".", exist_ok=True)
    if not os.path.exists(log_file_abs):
        with open(log_file_abs, "w", encoding="utf-8") as f:
            f.write("")

    print(f"[*] [WATCHER ACTIVE] Project '{project['id']}' ({service}) -> {log_file_abs}")
    
    recent_lines = []
    debounced_time = 0.0

    try:
        with open(log_file_abs, "r", encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            while not stop_flag.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.3)
                    continue

                cleaned = line.strip()
                if not cleaned:
                    continue

                recent_lines.append(cleaned)
                if len(recent_lines) > 30:
                    recent_lines.pop(0)

                # Check for crash patterns
                is_crash = any(p.search(cleaned) for p in error_patterns)
                now = time.time()
                if is_crash and (now - debounced_time > 10.0):
                    debounced_time = now
                    # Read any immediate trailing stack trace lines
                    time.sleep(0.25)
                    while True:
                        next_line = f.readline()
                        if not next_line:
                            break
                        cleaned_next = next_line.strip()
                        if cleaned_next:
                            recent_lines.append(cleaned_next)
                            if len(recent_lines) > 50:
                                recent_lines.pop(0)

                    print(f"\n🚨 [CRASH DETECTED in {service}] {cleaned}")
                    
                    try:
                        error_type = extract_exception_name(cleaned)
                        payload = {
                            "service": service,
                            "error_type": error_type,
                            "raw_logs": list(recent_lines),
                            "title": project.get("default_title") or f"{error_type} in {service}",
                            "description": project.get("default_description") or f"Unhandled failure detected in project '{project['id']}'.",
                            "remediation_patch": project.get("remediation_patch"),
                            "anti_pattern": project.get("anti_pattern"),
                            "anti_pattern_rationale": project.get("anti_pattern_rationale")
                        }
                        res = requests.post(COPILOT_TRIGGER_URL, json=payload, timeout=5.0)
                        if res.status_code == 201:
                            data = res.json()
                            print(f"[+] Incident Created: {data['ticket_id']} for {service}")
                            print(f"[+] Quick IDE Command: {data.get('ide_quick_load')}")
                    except Exception as e:
                        print(f"[!] Failed to dispatch alert: {e}")
    except Exception as e:
        print(f"[!] Log watcher error on {log_file_abs}: {e}")

def sync_project_watchers():
    """Dynamically detects new projects added to projects.yaml and spawns watchers."""
    projects = load_projects_config()
    with _LOCK:
        current_ids = {p["id"] for p in projects if "id" in p}

        # Start new watchers
        for proj in projects:
            p_id = proj.get("id")
            if not p_id or p_id in _ACTIVE_WATCHER_THREADS:
                continue

            stop_flag = threading.Event()
            t = threading.Thread(target=tail_project_log, args=(proj, stop_flag), daemon=True)
            t.start()
            _ACTIVE_WATCHER_THREADS[p_id] = t
            _ACTIVE_WATCHER_STOP_FLAGS[p_id] = stop_flag

        # Stop removed watchers
        removed_ids = set(_ACTIVE_WATCHER_THREADS.keys()) - current_ids
        for r_id in removed_ids:
            print(f"[*] Stopping watcher for removed project '{r_id}'")
            _ACTIVE_WATCHER_STOP_FLAGS[r_id].set()
            del _ACTIVE_WATCHER_THREADS[r_id]
            del _ACTIVE_WATCHER_STOP_FLAGS[r_id]

def run_project_watcher_daemon():
    print("[*] Project Watcher Daemon initialized. Dynamically monitoring projects.yaml...")
    while True:
        sync_project_watchers()
        time.sleep(2)

if __name__ == "__main__":
    run_project_watcher_daemon()
