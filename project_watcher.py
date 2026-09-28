import time
import os
import re
import yaml
import requests
import threading

COPILOT_TRIGGER_URL = os.getenv("COPILOT_TRIGGER_URL", "http://127.0.0.1:8000/api/v1/alerts/trigger")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "projects.yaml")

def load_projects_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"[!] {CONFIG_PATH} not found.")
        return []
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data.get("projects", [])

def tail_project_log(project: dict):
    log_file = project.get("log_file")
    service = project.get("service", "unknown-service")
    error_patterns = [re.compile(p, re.IGNORECASE) for p in project.get("error_patterns", [])]

    # Ensure log file exists
    os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else ".", exist_ok=True)
    if not os.path.exists(log_file):
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("")

    print(f"[*] Started watching project '{project['id']}' ({service}) -> {log_file}")
    
    recent_lines = []
    debounced_time = 0.0

    with open(log_file, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        while True:
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

            # Check if any error pattern matches
            is_crash = any(p.search(cleaned) for p in error_patterns)
            now = time.time()
            if is_crash and (now - debounced_time > 15.0):
                debounced_time = now
                print(f"\n🚨 [CRASH DETECTED in {service}] {cleaned}")
                
                # Automatically trigger Incident Copilot ticket
                try:
                    payload = {
                        "service": service,
                        "error_type": cleaned.split(":")[-1].strip() if ":" in cleaned else cleaned,
                        "raw_logs": list(recent_lines),
                        "title": project.get("default_title"),
                        "description": project.get("default_description"),
                        "remediation_patch": project.get("remediation_patch"),
                        "anti_pattern": project.get("anti_pattern"),
                        "anti_pattern_rationale": project.get("anti_pattern_rationale")
                    }
                    res = requests.post(COPILOT_TRIGGER_URL, json=payload, timeout=3.0)
                    if res.status_code == 201:
                        data = res.json()
                        print(f"[+] Successfully generated ticket: {data['ticket_id']}")
                        print(f"[+] Hindsight Injection: {data.get('hindsight_injected_runbook')}")
                except Exception as e:
                    print(f"[!] Failed to dispatch alert: {e}")

def start_all_project_watchers():
    projects = load_projects_config()
    threads = []
    for proj in projects:
        t = threading.Thread(target=tail_project_log, args=(proj,), daemon=True)
        t.start()
        threads.append(t)
    return threads

if __name__ == "__main__":
    print("[*] Starting Multi-Project Background Watcher from projects.yaml...")
    watchers = start_all_project_watchers()
    while True:
        time.sleep(1)
