import time
import os
import requests

COPILOT_INGEST_URL = os.getenv("COPILOT_INGEST_URL", "http://127.0.0.1:8000/api/v1/logs/ingest")
LOG_FILE = os.path.join(os.path.dirname(__file__), "checkout.log")

def tail_logs():
    print(f"[*] Starting Log Tailer Agent watching {LOG_FILE} -> {COPILOT_INGEST_URL}")

    # Ensure log file exists
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        # Seek to end
        f.seek(0, os.SEEK_END)

        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue

            cleaned_line = line.strip()
            if not cleaned_line:
                continue

            try:
                res = requests.post(
                    COPILOT_INGEST_URL,
                    json={"service": "checkout-service", "log_line": cleaned_line},
                    timeout=2.0
                )
                if res.status_code == 200:
                    data = res.json()
                    if data.get("status") == "crash_detected":
                        print(f"\n🚨 [CRASH INTERCEPTED] Generated Incident Ticket: {data['ticket']['ticket_id']}")
            except Exception as e:
                # Silently wait if copilot is temporarily restarting
                pass

if __name__ == "__main__":
    tail_logs()
