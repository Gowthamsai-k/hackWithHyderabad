import time
import requests

BASE_URL = "http://127.0.0.1:8000"

def run_hackathon_demo():
    print("=" * 70)
    print("RUN 1: NOVEL INCIDENT (BASELINE BEHAVIOR)")
    print("=" * 70)

    # Simulate realistic server logs with traffic lead-up and connection timeout cascade
    novel_logs = [
        "2026-09-28T14:00:00 INFO Ingress traffic surge: 1200 req/s on /checkout",
        "2026-09-28T14:00:01 ERROR ConnectionPool timeout: Max connections (10) exhausted under load"
    ] + ["2026-09-28T14:00:02 ERROR ConnectionPool timeout: Max connections (10) exhausted under load"] * 40

    # 1. Trigger Alert
    t1_res = requests.post(f"{BASE_URL}/api/v1/alerts/trigger", json={
        "service": "checkout-service",
        "error_type": "Redis ConnectionPool timeout",
        "raw_logs": novel_logs
    }).json()

    t1_id = t1_res["ticket_id"]
    print(f"\n[+] Ticket Generated: {t1_id}")
    print(f"[+] Hindsight Injection: {t1_res['hindsight_injected_runbook']}")
    print(f"[+] IDE Context Command: {t1_res['ide_quick_load']}")

    # 2. Simulate Engineer Triage Chat
    print("\n[*] Simulating Engineer Triage Discussion in Ticket Thread...")
    requests.post(f"{BASE_URL}/api/v1/tickets/{t1_id}/comment", json={
        "author": "Jane", "text": "Saw the alert. Initiating rolling restart on checkout-service pods."
    })
    requests.post(f"{BASE_URL}/api/v1/tickets/{t1_id}/comment", json={
        "author": "Bob", "text": "Restart completed, but errors re-triggered immediately. Still crashing."
    })
    requests.post(f"{BASE_URL}/api/v1/tickets/{t1_id}/comment", json={
        "author": "Jane", "text": "Connection pool is starving. Patched Helm values to scale max_connections from 10 to 50."
    })
    requests.post(f"{BASE_URL}/api/v1/tickets/{t1_id}/comment", json={
        "author": "Bob", "text": "Traffic stabilized. 200 OKs verified across ingress. Problem resolved."
    })

    # 3. Resolve Ticket -> Triggers Asynchronous Idle-Path Worker
    print(f"\n[*] Resolving {t1_id}. Triggering Idle-Path Worker...")
    requests.post(f"{BASE_URL}/api/v1/tickets/{t1_id}/resolve")
    print("[*] Waiting 6 seconds for post-mortem extraction and Hindsight retention...")
    time.sleep(6)

    print("\n" + "=" * 70)
    print("RUN 2: RECURRING INCIDENT WEEKS LATER (HINDSIGHT PAYOFF)")
    print("=" * 70)

    # Same error occurs on checkout-service
    t2_res = requests.post(f"{BASE_URL}/api/v1/alerts/trigger", json={
        "service": "checkout-service",
        "error_type": "Redis ConnectionPool timeout",
        "raw_logs": [
            "2026-10-15T09:00:00 INFO Peak traffic spike detected",
            "2026-10-15T09:00:01 ERROR ConnectionPool timeout: Max connections (10) exhausted under load"
        ]
    }).json()

    print(f"\n[+] Second Ticket Generated: {t2_res['ticket_id']}")
    print(f"\n🧠 HINDSIGHT LIVING MEMORY INJECTED INTO RUNBOOK:")
    print(t2_res['hindsight_injected_runbook'])

    print("\n[+] Inspecting Rendered Context Markdown for Claude Code / Cursor:")
    md_content = requests.get(f"{BASE_URL}/api/v1/tickets/{t2_res['ticket_id']}/context.md").text
    print("-" * 50)
    print(md_content)
    print("-" * 50)

if __name__ == "__main__":
    run_hackathon_demo()
