import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from pydantic import BaseModel
from schemas import AlertTriggerPayload, CommentPayload, Ticket
from filters import filter_logs, filter_chat
from hindsight_service import init_bank, recall_memory, get_all_memories, reset_memory_bank
from synthesizer import run_idle_post_mortem
from watcher import BackgroundLogWatcher

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
log_watcher = BackgroundLogWatcher(buffer_size=100, debounce_window_sec=30.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_bank()
    yield

app = FastAPI(title="Autonomous Incident Copilot", lifespan=lifespan)

TICKETS: Dict[str, Ticket] = {}

class LogIngestPayload(BaseModel):
    service: str = "checkout-service"
    log_line: str

@app.get("/")
def get_dashboard():
    dashboard_path = os.path.join(STATIC_DIR, "dashboard.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path, media_type="text/html")
    return {
        "service": "Autonomous Incident Copilot",
        "status": "operational",
        "tickets_count": len(TICKETS)
    }

@app.post("/api/v1/alerts/trigger", status_code=201)
def trigger_alert(payload: AlertTriggerPayload):
    ticket_id = f"INC-{len(TICKETS) + 101}"

    # Fast-Path: Query Hindsight memory (Read-Only)
    recalled_runbook = recall_memory(payload.service, payload.error_type)
    is_recurring = bool(recalled_runbook and "No prior runbook" not in recalled_runbook)

    now = datetime.now(timezone.utc)
    agent_trace = [
        {
            "phase": "FAST-PATH",
            "timestamp": now.isoformat(),
            "event": "Outage Signal Ingested",
            "detail": f"Received {len(payload.raw_logs)} telemetry lines for service '{payload.service}'. Fingerprint debounced."
        },
        {
            "phase": "FAST-PATH",
            "timestamp": now.isoformat(),
            "event": "Living Memory Multi-Arm Recall",
            "detail": "Queried Hindsight (Semantic + BM25 + Knowledge Graph) with zero hot-path LLM latency."
        },
        {
            "phase": "FAST-PATH",
            "timestamp": now.isoformat(),
            "event": "Living Runbook Injected" if is_recurring else "Cold Start Initialized",
            "detail": "Historical verified fix & anti-pattern warning injected directly into ticket." if is_recurring else "No prior history detected in bank; cold start initialized."
        },
        {
            "phase": "FAST-PATH",
            "timestamp": now.isoformat(),
            "event": "Context Markdown Generated",
            "detail": f"Agentic context available via curl endpoint for Claude Code / Cursor."
        }
    ]

    ticket = Ticket(
        id=ticket_id,
        service=payload.service,
        severity="P1",
        status="OPEN",
        created_at=now,
        raw_logs=payload.raw_logs,
        comments=[],
        hindsight_runbook=recalled_runbook or "First occurrence: No prior runbook found in Hindsight.",
        is_recurring=is_recurring,
        reduction_stats=None,
        agent_trace=agent_trace
    )
    TICKETS[ticket_id] = ticket

    return {
        "ticket_id": ticket.id,
        "service": ticket.service,
        "status": ticket.status,
        "is_recurring": is_recurring,
        "hindsight_injected_runbook": ticket.hindsight_runbook,
        "ide_quick_load": f"curl -s http://localhost:8000/api/v1/tickets/{ticket.id}/context.md > .incident_context.md",
        "agent_trace": ticket.agent_trace
    }

@app.post("/api/v1/logs/ingest")
def ingest_log_line(payload: LogIngestPayload):
    """
    Ingests live application log lines into the passive ring buffer.
    Automatically triggers Fast-Path alert if an un-debounced crash signature is detected.
    """
    detected_error = log_watcher.push_line(payload.log_line, service=payload.service)
    if detected_error:
        raw_slice = log_watcher.get_context_slice(50)
        alert_payload = AlertTriggerPayload(
            service=payload.service,
            error_type=detected_error,
            raw_logs=raw_slice
        )
        ticket_res = trigger_alert(alert_payload)
        return {
            "status": "crash_detected",
            "error_type": detected_error,
            "ticket": ticket_res
        }
    return {"status": "buffered", "ring_buffer_size": len(log_watcher.ring_buffer)}

@app.get("/api/v1/tickets")
def list_tickets() -> List[Ticket]:
    return list(TICKETS.values())

@app.get("/api/v1/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> Ticket:
    if ticket_id not in TICKETS:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return TICKETS[ticket_id]

@app.post("/api/v1/tickets/{ticket_id}/comment")
def add_comment(ticket_id: str, comment: CommentPayload):
    if ticket_id not in TICKETS:
        raise HTTPException(status_code=404, detail="Ticket not found")

    now = datetime.now(timezone.utc)
    comment_record = {
        "author": comment.author,
        "text": comment.text,
        "timestamp": now.isoformat()
    }
    TICKETS[ticket_id].comments.append(comment_record)
    TICKETS[ticket_id].agent_trace.append({
        "phase": "TRIAGE",
        "timestamp": now.isoformat(),
        "event": "Triage Comment Recorded",
        "detail": f"{comment.author}: {comment.text[:80]}..."
    })
    return {"status": "comment_added", "ticket_id": ticket_id, "comment": comment_record}

def _async_idle_worker(ticket_id: str, service: str, clean_logs: list, clean_chat: list, closed_at: datetime):
    now = datetime.now(timezone.utc)
    if ticket_id in TICKETS:
        TICKETS[ticket_id].agent_trace.append({
            "phase": "IDLE-PATH",
            "timestamp": now.isoformat(),
            "event": "Information Reduction Funnel",
            "detail": f"Collapsed repetitive log storms and stripped social chatter from triage thread."
        })
        TICKETS[ticket_id].agent_trace.append({
            "phase": "IDLE-PATH",
            "timestamp": now.isoformat(),
            "event": "LLM Synthesis Pass (Groq)",
            "detail": f"Analyzing sanitized bundle to extract root causes, failed steps, and verified fixes."
        })

    post_mortem = run_idle_post_mortem(ticket_id, service, clean_logs, clean_chat, closed_at)

    if ticket_id in TICKETS:
        TICKETS[ticket_id].final_post_mortem = post_mortem
        TICKETS[ticket_id].agent_trace.append({
            "phase": "IDLE-PATH",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "Hindsight Memory Consolidated",
            "detail": f"Permanently stored verified fix and anti-pattern warning into Hindsight bank: incident-ops-bank"
        })

@app.post("/api/v1/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, background_tasks: BackgroundTasks):
    if ticket_id not in TICKETS:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket = TICKETS[ticket_id]
    ticket.status = "RESOLVED"
    closed_at = datetime.now(timezone.utc)

    # Information Reduction Funnel: Compress before LLM ingestion
    clean_logs = filter_logs(ticket.raw_logs)
    clean_chat = filter_chat(ticket.comments)

    ticket.reduction_stats = {
        "raw_logs_count": len(ticket.raw_logs),
        "clean_logs_count": len(clean_logs),
        "raw_comments_count": len(ticket.comments),
        "clean_comments_count": len(clean_chat),
        "log_compression_pct": round((1.0 - (len(clean_logs) / max(len(ticket.raw_logs), 1))) * 100, 1)
    }

    # Queue Idle-Path synthesis worker asynchronously
    background_tasks.add_task(
        _async_idle_worker,
        ticket.id,
        ticket.service,
        clean_logs,
        clean_chat,
        closed_at
    )

    return {
        "status": "ticket_resolved",
        "ticket_id": ticket.id,
        "idle_worker": "post_mortem_synthesis_queued",
        "reduction_stats": ticket.reduction_stats
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
```

## 3. Institutional Runbook Memory (from Hindsight)
{ticket.hindsight_runbook}

## 4. Remediation Invariant
Any suggested fix must focus strictly on deployment or infrastructure configurations.
Do not modify core application business logic.
"""

@app.get("/api/v1/hindsight/memories")
def get_hindsight_memories():
    return {
        "bank_id": "incident-ops-bank",
        "memories": get_all_memories()
    }

@app.get("/api/v1/realtime/status")
def get_realtime_app_status():
    """Polls real-time checkout-service metrics on port 8050."""
    import requests
    try:
        res = requests.get("http://127.0.0.1:8050/metrics", timeout=1.0)
        return {"online": True, "metrics": res.json()}
    except Exception:
        return {"online": False, "metrics": None}

@app.post("/api/v1/realtime/surge")
def trigger_realtime_surge(concurrency: int = 25):
    """Triggers real concurrent traffic against the checkout-service."""
    from sample_service.traffic_generator import generate_traffic_surge
    result = generate_traffic_surge(concurrency)
    return {"status": "surge_completed", "results": result}

@app.post("/api/v1/realtime/restart")
def trigger_realtime_restart():
    """Triggers rolling restart simulation on the checkout-service."""
    from sample_service.traffic_generator import apply_rolling_restart
    result = apply_rolling_restart()
    return {"status": "restarted", "result": result}

@app.post("/api/v1/realtime/patch-helm")
def trigger_realtime_helm_patch(pool_size: int = 50):
    """Applies Helm values patch to scale pool on checkout-service."""
    from sample_service.traffic_generator import apply_helm_patch
    result = apply_helm_patch(pool_size)
    return {"status": "patched", "result": result}

@app.post("/api/v1/demo/reset")
def reset_demo():
    """Resets all tickets and clears memory bank for a fresh demo."""
    import requests
    TICKETS.clear()
    reset_memory_bank()
    log_watcher.clear()
    # Reset pool size back to 10
    try:
        requests.post("http://127.0.0.1:8050/admin/scale-pool", params={"new_pool_size": 10}, timeout=1.0)
    except Exception:
        pass
    return {"status": "demo_environment_reset"}
