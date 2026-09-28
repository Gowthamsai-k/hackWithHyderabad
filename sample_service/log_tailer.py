import time
import os
import requests
from dotenv import load_dotenv
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

load_dotenv()

def get_env_var(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'\"")
    return val

COPILOT_PORT = get_env_var("PORT", "8000")
COPILOT_HOST = get_env_var("HOST", "127.0.0.1")
if COPILOT_HOST == "0.0.0.0":
    COPILOT_HOST = "127.0.0.1"

COPILOT_INGEST_URL = get_env_var("COPILOT_INGEST_URL", f"http://{COPILOT_HOST}:{COPILOT_PORT}/api/v1/logs/ingest")
LOG_FILE = get_env_var("CHECKOUT_LOG_FILE", os.path.join(os.path.dirname(__file__), "checkout.log"))
SERVICE_NAME = get_env_var("CHECKOUT_SERVICE_NAME", "checkout-service")

# Initialize Presidio engines once
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

def sanitize_log_line(log_text: str) -> str:
    """Uses Microsoft Presidio to detect and redact sensitive PII (Emails, Names, Phone numbers, Credit Cards, SSNs, IPs)."""
    results = analyzer.analyze(
        text=log_text,
        entities=["EMAIL_ADDRESS", "PERSON", "PHONE_NUMBER", "CREDIT_CARD", "IP_ADDRESS", "US_SSN"],
        language="en"
    )
    anonymized_result = anonymizer.anonymize(
        text=log_text,
        analyzer_results=results
    )
    return anonymized_result.text

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

            # Redact sensitive data using Microsoft Presidio before sending to LLM/Copilot
            sanitized_line = sanitize_log_line(cleaned_line)

            try:
                res = requests.post(
                    COPILOT_INGEST_URL,
                    json={"service": SERVICE_NAME, "log_line": sanitized_line},
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
