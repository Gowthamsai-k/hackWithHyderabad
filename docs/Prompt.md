

# MASTER ARCHITECTURE & SPECIFICATION: AUTONOMOUS INCIDENT COPILOT WITH LIVING HINDSIGHT MEMORY

## 1. PROJECT OVERVIEW & CORE NOVELTY
Traditional AI DevOps copilots and incident chatbots fail because:
1. **Intrusive Hot-Path Latency:** They execute heavy LLM inference during active outages, causing rate limits, latency, and conversational clutter when engineers need immediate, quiet answers.
2. **Naive Flat Vector Search:** Conventional RAG confuses semantically similar errors (e.g., `504 Gateway Timeout`) across completely different microservices.
3. **Loss of Negative Knowledge:** Post-mortems only record what worked. They fail to record what engineers tried that **did not work**, forcing future on-call engineers to repeat identical dead-end troubleshooting steps.
4. **Context Friction for Coding Agents:** Engineers working in modern IDEs/terminals (Claude Code, Cursor) often prompt with incomplete understanding. Silently writing context files directly into git repositories pollutes working trees, breaks dirty-tree CI checks, and causes multi-repo routing confusion.

### The Architectural Solution: Decoupled Fast-Path / Idle-Path Engine
- **Passive Background Listener:** Continuously monitors log streams via an in-memory ring buffer (50–100 lines) with regex error detection and fingerprint debouncing.
- **Fast-Path (During Outage):** Instant, deterministic ticket creation in milliseconds. Attaches raw logs as hidden metadata, queries Hindsight via read-only multi-arm recall for verified historical runbooks, and serves a clean, verifiable Context Markdown Pack via a `curl` endpoint for Claude Code/Cursor.
- **Human Triage Collaboration:** Engineers triage naturally in the ticket thread without intrusive bot interruptions.
- **Information Reduction Funnel:** When an incident resolves, raw logs and conversational chatter are filtered deterministically, collapsing repetitive error storms and stripping casual banter.
- **Idle-Path Worker (Post-Incident):** Executes asynchronous post-mortem synthesis via Groq LLM (with strict JSON schema enforcement) and permanently retains verified root causes, restorative fixes, failed attempts, and anti-pattern warnings into the Hindsight Knowledge Graph.
2. END-TO-END SYSTEM TOPOLOGY
                         [ APPLICATION SERVICES ]
                                    │
                               (Log Stream)
                                    ▼
                        [ Background Log Watcher ]
                        (Ring Buffer: last 100 lines)
                                    │
            ┌───────────────────────┴───────────────────────┐
            │ [CRASH DETECTED]                              │ [SERVER IDLE]
            ▼                                               ▼
┌───────────────────────────────┐               ┌───────────────────────────────┐
│     FAST-PATH: OUTAGE BUS     │               │    IDLE-PATH: ASYNC WORKER    │
├───────────────────────────────┤               ├───────────────────────────────┤
│ 1. Slice: Pre-crash + Trace   │               │ 1. Triggered on: Ticket Close │
│ 2. Query Hindsight: Read-Only │               │    or Off-Peak Log Window     │
│    (Recall prior runbooks)    │               │ 2. Fetch full Incident Bundle │
│ 3. Create Ticket in CRM:      │               │    (Logs + Full Team Chat)    │
│    - Attach Hidden Log Blob   │               │ 3. LLM Extraction Pass (Groq) │
│    - Inject Memory Runbook    │               │    - Verified Root Cause      │
│    - Route by Dept & Priority │               │    - Failed/Discarded Steps   │
│ 4. Expose `context.md` route  │               │    - Restorative Fix          │
│    for `curl | claude`        │               │ 4. Hindsight Retain & Reflect │
└───────────────┬───────────────┘               │    - Update Causal Graph      │
                │                               │    - Deprecate Bad Runbooks   │
                ▼                               └───────────────────────────────┘
┌───────────────────────────────┐                               ▲
│   INCIDENT CRM / WEB DASH     │                               │
│   (Team Chat & Remediation)   │                               │
│                               │                               │
│  "Tried rolling restart..."   │                               │
│  "Applied Helm pool patch..." │                               │
│  Status -> [ RESOLVED ] ──────┴───────────────────────────────┘
3. TECHNICAL SPECIFICATIONS & DEPENDENCIES
Python Version: 3.11+

API Framework: fastapi, uvicorn, pydantic>=2.0

Memory Subsystem: hindsight-client (connecting to Hindsight Cloud or local instance at port 8888)

LLM Synthesis: groq (qwen/qwen3-32b or openai/gpt-oss-120b) with JSON mode

Utilities: python-dotenv, requests

4. COMPLETE SOURCE CODE IMPLEMENTATION
Directory Structure
Plaintext
incident-copilot/
├── .env
├── requirements.txt
├── schemas.py
├── filters.py
├── hindsight_service.py
├── synthesizer.py
├── main.py
└── demo.py
File: requirements.txt
Plaintext
fastapi>=0.110.0
uvicorn>=0.28.0
pydantic>=2.6.0
groq>=0.5.0
hindsight-client>=0.1.0
python-dotenv>=1.0.0
requests>=2.31.0
File: .env
Code snippet
HINDSIGHT_BASE_URL=[https://api.hindsight.vectorize.io](https://api.hindsight.vectorize.io)
HINDSIGHT_API_KEY=your_hindsight_api_key_here
GROQ_API_KEY=your_groq_api_key_here
BANK_ID=incident-ops-bank
File: schemas.py
Python
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class AlertTriggerPayload(BaseModel):
    service: str = Field(..., example="checkout-service")
    error_type: str = Field(..., example="Redis::ConnectionTimeout")
    raw_logs: List[str]

class CommentPayload(BaseModel):
    author: str
    text: str

class PostMortemExtraction(BaseModel):
    root_cause: str = Field(description="The verified technical root cause.")
    failed_attempts: List[str] = Field(description="Actions tried that failed or caused regressions.")
    verified_fix: str = Field(description="The specific action that resolved the outage.")
    anti_pattern_warning: str = Field(description="Actionable rule warning future engineers against dead-end steps.")

class Ticket(BaseModel):
    id: str
    service: str
    severity: str
    status: str  # OPEN, RESOLVED
    created_at: datetime
    raw_logs: List[str]
    comments: List[Dict[str, Any]] = []
    hindsight_runbook: Optional[str] = None
    final_post_mortem: Optional[PostMortemExtraction] = None
File: filters.py
Python
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
File: hindsight_service.py
Python
import os
from datetime import datetime
from typing import Optional
from hindsight_client import Hindsight

HINDSIGHT_URL = os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888")
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "")
BANK_ID = os.getenv("BANK_ID", "incident-ops-bank")

client = Hindsight(base_url=HINDSIGHT_URL, api_key=HINDSIGHT_API_KEY)

def init_bank():
    """Ensures the Hindsight memory bank exists with appropriate cognitive settings."""
    try:
        client.create_bank(
            bank_id=BANK_ID,
            name="Incident SRE Brain",
            mission="Retain incident post-mortems, verified runbooks, failed attempts, and anti-pattern warnings.",
            disposition={"skepticism": 2, "literalism": 4, "empathy": 1}
        )
    except Exception:
        pass

def recall_memory(service: str, error_type: str) -> Optional[str]:
    """Queries Hindsight using multi-arm retrieval (Semantic + BM25 + Graph)."""
    try:
        memories = client.recall(
            bank_id=BANK_ID,
            query=f"Past fixes, root causes, and failed attempts for {service} encountering {error_type}",
            budget="high"
        )
        if memories and memories.results:
            return "\n".join([f"- {r.text}" for r in memories.results[:3]])
    except Exception as e:
        print(f"[!] Hindsight recall failed: {e}")
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
    client.retain(
        bank_id=BANK_ID,
        content=content,
        context=f"service:{service}:incidents",
        timestamp=closed_at,
        metadata={"ticket_id": ticket_id, "service": service, "type": "verified_post_mortem"},
        retain_async=False
    )
    print(f"[*] Successfully retained post-mortem for {ticket_id} in Hindsight bank: {BANK_ID}")
File: synthesizer.py
Python
import os
import json
import re
from datetime import datetime
from groq import Groq
from schemas import PostMortemExtraction
from hindsight_service import retain_post_mortem

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def clean_llm_json(raw_text: str) -> dict:
    """Strips markdown code fences and returns parsed dictionary."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)

def run_idle_post_mortem(ticket_id: str, service: str, filtered_logs: list, filtered_chat: list, closed_at: datetime):
    """Synthesizes root causes, failed steps, and fixes from the complete incident bundle."""
    prompt = f"""
You are an expert SRE Post-Mortem Compiler. Analyze this resolved incident bundle for service '{service}'.

SANITIZED INCIDENT LOGS:
{json.dumps(filtered_logs, indent=2)}

FILTERED TRIAGE CHAT:
{json.dumps(filtered_chat, indent=2)}

Extract the incident facts into valid JSON matching this exact structure:
{{
  "root_cause": "Detailed technical root cause",
  "failed_attempts": ["List of attempted actions that failed or had no effect"],
  "verified_fix": "The specific action that resolved the outage",
  "anti_pattern_warning": "Warning future engineers what NOT to do based on failed attempts"
}}
Output raw JSON only. Do NOT include markdown code blocks.
"""

    response = groq_client.chat.completions.create(
        model="qwen/qwen3-32b",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    parsed = clean_llm_json(response.choices[0].message.content)
    post_mortem = PostMortemExtraction(**parsed)

    # Ingest permanently into Hindsight memory
    retain_post_mortem(ticket_id, service, post_mortem, closed_at)
File: main.py
Python
from datetime import datetime
from typing import Dict
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse
from schemas import AlertTriggerPayload, CommentPayload, Ticket
from filters import filter_logs, filter_chat
from hindsight_service import init_bank, recall_memory
from synthesizer import run_idle_post_mortem

app = FastAPI(title="Autonomous Incident Copilot")

TICKETS: Dict[str, Ticket] = {}

@app.on_event("startup")
def on_startup():
    init_bank()

@app.post("/api/v1/alerts/trigger", status_code=201)
def trigger_alert(payload: AlertTriggerPayload):
    ticket_id = f"INC-{len(TICKETS) + 101}"

    # Fast-Path: Query Hindsight memory (Read-Only)
    recalled_runbook = recall_memory(payload.service, payload.error_type)

    ticket = Ticket(
        id=ticket_id,
        service=payload.service,
        severity="P1",
        status="OPEN",
        created_at=datetime.utcnow(),
        raw_logs=payload.raw_logs,
        comments=[],
        hindsight_runbook=recalled_runbook or "First occurrence: No prior runbook found in Hindsight."
    )
    TICKETS[ticket_id] = ticket

    return {
        "ticket_id": ticket.id,
        "service": ticket.service,
        "status": ticket.status,
        "hindsight_injected_runbook": ticket.hindsight_runbook,
        "ide_quick_load": f"curl -s http://localhost:8000/api/v1/tickets/{ticket.id}/context.md > .incident_context.md"
    }

@app.post("/api/v1/tickets/{ticket_id}/comment")
def add_comment(ticket_id: str, comment: CommentPayload):
    if ticket_id not in TICKETS:
        raise HTTPException(status_code=404, detail="Ticket not found")

    TICKETS[ticket_id].comments.append({
        "author": comment.author,
        "text": comment.text,
        "timestamp": datetime.utcnow().isoformat()
    })
    return {"status": "comment_added", "ticket_id": ticket_id}

@app.post("/api/v1/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, background_tasks: BackgroundTasks):
    if ticket_id not in TICKETS:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket = TICKETS[ticket_id]
    ticket.status = "RESOLVED"
    closed_at = datetime.utcnow()

    # Information Reduction Funnel: Compress before LLM ingestion
    clean_logs = filter_logs(ticket.raw_logs)
    clean_chat = filter_chat(ticket.comments)

    # Queue Idle-Path synthesis worker asynchronously
    background_tasks.add_task(
        run_idle_post_mortem,
        ticket.id,
        ticket.service,
        clean_logs,
        clean_chat,
        closed_at
    )

    return {
        "status": "ticket_resolved",
        "ticket_id": ticket.id,
        "idle_worker": "post_mortem_synthesis_queued"
    }

@app.get("/api/v1/tickets/{ticket_id}/context.md", response_class=PlainTextResponse)
def get_incident_context_markdown(ticket_id: str):
    """
    Renders pure markdown context for terminal and IDE agents (Claude Code, Cursor).
    Enables single-command loading without repo pollution:
    $ curl -s http://localhost:8000/api/v1/tickets/INC-101/context.md | claude
    """
    if ticket_id not in TICKETS:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket = TICKETS[ticket_id]
    log_sample = "\n".join(ticket.raw_logs[:15])

    return f"""# INCIDENT CONTEXT: {ticket.id} ({ticket.service})
> Auto-generated by Incident Copilot at {ticket.created_at.isoformat()}Z.

## 1. Verified Failure Signature
- Service: {ticket.service}
- Status: {ticket.status}
- Severity: {ticket.severity}

## 2. Telemetry & Log Snippet
```text
{log_sample}
3. Institutional Runbook Memory (from Hindsight)
{ticket.hindsight_runbook}

4. Remediation Invariant
Any suggested fix must focus strictly on deployment or infrastructure configurations.
Do not modify core application business logic.
"""


### File: `demo.py`
```python
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
    print("[*] Waiting 6 seconds for Groq extraction and Hindsight retention...")
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
5. EXECUTION & VERIFICATION INSTRUCTIONS FOR ANTIGRAVITY
Install dependencies:

Bash
pip install -r requirements.txt
Start the FastAPI server:

Bash
uvicorn main:app --reload --port 8000
In a separate terminal, execute the demo runner:

Bash
python demo.py
Verify the output:

Run 1: Demonstrates novel incident creation with zero prior context.

Idle Worker: Asynchronously extracts the post-mortem via Groq without blocking.

Run 2: Demonstrates immediate recall from Hindsight, highlighting the verified fix (max_connections=50) and the anti-pattern warning (Do not perform rolling restarts).

IDE Context: Renders a clean markdown document accessible via curl for Claude Code or Cursor.