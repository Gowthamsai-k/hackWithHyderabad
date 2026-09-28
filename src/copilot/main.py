import os
import sys
import platform
from datetime import datetime, timezone
from typing import Dict, List, Optional
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from pydantic import BaseModel
from .schemas import AlertTriggerPayload, CommentPayload, Ticket
from .filters import filter_logs, filter_chat, apply_context_budget
from .hindsight_service import init_bank, recall_memory, get_all_memories, reset_memory_bank
from .synthesizer import run_idle_post_mortem, synthesize_remediation_and_anti_pattern
from .watcher import BackgroundLogWatcher
from .supabase_service import store_incident_report, get_past_reports

load_dotenv()

def get_env_var(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'\"")
    return val

BANK_ID = get_env_var("BANK_ID", "incident-ops-bank")
DEFAULT_REGION = get_env_var("DEFAULT_REGION", "us-east-1a")
SEED_DEMO_TICKETS = get_env_var("SEED_DEMO_TICKETS", "false").lower() in ("true", "1", "yes")

CHECKOUT_SERVICE_HOST = get_env_var("CHECKOUT_SERVICE_HOST", "127.0.0.1")
CHECKOUT_SERVICE_PORT = get_env_var("CHECKOUT_SERVICE_PORT", "8050")
CHECKOUT_BASE_URL = f"http://{CHECKOUT_SERVICE_HOST}:{CHECKOUT_SERVICE_PORT}"

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static"))
log_watcher = BackgroundLogWatcher(buffer_size=100, debounce_window_sec=30.0)

TICKETS: Dict[str, Ticket] = {}

def get_system_runtime_info():
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "arch": platform.machine(),
        "python_version": sys.version.split()[0],
    }

def seed_initial_tickets():
    """Optionally seeds initial production incident tickets if SEED_DEMO_TICKETS is set to true."""
    if TICKETS or not SEED_DEMO_TICKETS:
        return

    now = datetime.now(timezone.utc)
    t104 = Ticket(
        id="INC-104",
        service="checkout-service",
        severity="P1",
        status="OPEN",
        created_at=now,
        title="Redis Pool Starvation in checkout-service Pods",
        description="Connections exhausted during flash checkout load spike; transactions failing with timeout cascade to upstream payment router.",
        region=DEFAULT_REGION,
        degraded_pods="4 / 12 pods",
        error_spike="+840% p99",
        detection_source="TEMPR v2",
        blast_radius=["payment-gateway:9042", "cart-cache-redis.internal", "notification-worker-pool"],
        raw_logs=[
            "Redis::ConnectionPool::TimeoutError: Waited 2.000 sec, 0 pool tokens available",
            "  at checkout/db/redis.go:142 in AcquireClientWithRetry()",
            "  at checkout/handlers/cart.go:88 in CommitCartReservation()"
        ],
        remediation_patch="""# checkout-service/k8s/deployment.yaml
- REDIS_POOL_MAX_ACTIVE: 20
+ REDIS_POOL_MAX_ACTIVE: 80
+ REDIS_POOL_IDLE_TIMEOUT: 45s""",
        anti_pattern="DO NOT perform rolling pod restarts (e.g. kubectl rollout restart deployment/checkout-service).",
        anti_pattern_rationale="In past trace INC-101, rolling restarts under active ingress re-triggered immediate socket starvation, dropped 42 in-flight cart reservations, and amplified p99 latency spikes by +35%.",
        comments=[
            {"author": "Jane (SRE)", "text": "Saw the alert. Initiating rolling restart on checkout-service pods.", "timestamp": now.isoformat()},
            {"author": "Bob (Infra)", "text": "Restart completed, but errors re-triggered immediately. Still crashing.", "timestamp": now.isoformat()}
        ],
        hindsight_runbook="Past fix on checkout-service: Patched Helm values to scale max_connections from 20 to 80. Anti-pattern warning: Do not perform rolling restarts; they re-trigger connection pool exhaustion.",
        is_recurring=True,
        agent_trace=[
            {"phase": "FAST-PATH", "timestamp": now.isoformat(), "event": "Outage Signal Ingested", "detail": "TEMPR v2 alert stream debounced."},
            {"phase": "FAST-PATH", "timestamp": now.isoformat(), "event": "Living Memory Injected", "detail": "Recalled prior runbook & anti-pattern."}
        ],
        environment_metadata=get_system_runtime_info()
    )

    t103 = Ticket(
        id="INC-103",
        service="payment-gateway",
        severity="P1",
        status="OPEN",
        created_at=now,
        title="Upstream HTTP 504 Timeout Cascade",
        description="Payment router thread exhaustion propagating from database lock contention on checkout balances.",
        region=DEFAULT_REGION,
        degraded_pods="6 / 18 pods",
        error_spike="+420% p99",
        detection_source="WATCHER v3",
        blast_radius=["order-processor:8080", "stripe-egress-proxy"],
        raw_logs=[
            "Gateway::HTTPTimeout: Upstream read timeout after 5000ms on /v1/charge",
            "  at payment/handlers/charge.go:54 in DispatchPaymentRequest()"
        ],
        remediation_patch="""# payment-gateway/config/timeouts.json
- UPSTREAM_TIMEOUT_MS: 5000
+ UPSTREAM_TIMEOUT_MS: 12000
+ CIRCUIT_BREAKER_TRIP_COUNT: 10""",
        anti_pattern="DO NOT decrease downstream client request timeouts.",
        anti_pattern_rationale="Shortening client timeouts triggered retry cascades that doubled incoming request load on the database.",
        comments=[{"author": "DevOps", "text": "Circuit breaker tripped. Investigating balance DB latency.", "timestamp": now.isoformat()}],
        hindsight_runbook="Past fix on payment-gateway: Raised upstream timeout from 5000ms to 12000ms and adjusted circuit breaker thresholds.",
        is_recurring=True,
        environment_metadata=get_system_runtime_info()
    )

    t102 = Ticket(
        id="INC-102",
        service="auth-service",
        severity="P2",
        status="RESOLVED",
        created_at=now,
        title="JWT Token Verification Latency Spike",
        description="Public key cache invalidation loop causing unthrottled JWKS endpoint requests.",
        region=DEFAULT_REGION,
        degraded_pods="2 / 8 pods",
        error_spike="+180% p99",
        detection_source="HINDSIGHT",
        blast_radius=["api-gateway", "session-manager"],
        raw_logs=[
            "Auth::JWKSCacheMiss: Key ID 'key_2026_09' expired; fetching remote jwks.json",
            "  at auth/cache/jwks.go:32 in GetPublicKeyWithTTL()"
        ],
        remediation_patch="""# auth-service/env.yaml
- JWKS_CACHE_TTL_SEC: 60
+ JWKS_CACHE_TTL_SEC: 3600""",
        anti_pattern="DO NOT flush public key cache across all instances simultaneously.",
        anti_pattern_rationale="Simultaneous cache flush causes stampedes against remote JWKS endpoints.",
        comments=[{"author": "SecOps", "text": "Patched JWKS cache TTL from 60s to 3600s. Cache hit ratio restored.", "timestamp": now.isoformat()}],
        hindsight_runbook="Verified Fix: Bumped JWKS_CACHE_TTL_SEC to 3600 to prevent cache stampedes.",
        is_recurring=False,
        environment_metadata=get_system_runtime_info()
    )

    TICKETS[t102.id] = t102
    TICKETS[t103.id] = t103
    TICKETS[t104.id] = t104
    print(f"[*] Seeded {len(TICKETS)} production incident tickets into environment.")

def restore_tickets_from_supabase():
    """Restores past resolved incident reports from Supabase into the TICKETS map on server restart."""
    past_reports = get_past_reports(limit=100)
    for rep in past_reports:
        tid = rep.get("ticket_id")
        if not tid or tid in TICKETS:
            continue
        try:
            created_at = datetime.fromisoformat(rep.get("created_at")) if rep.get("created_at") else datetime.now(timezone.utc)
        except Exception:
            created_at = datetime.now(timezone.utc)

        t = Ticket(
            id=tid,
            service=rep.get("service", "unknown-service"),
            severity="P1",
            status="RESOLVED",
            created_at=created_at,
            raw_logs=rep.get("raw_logs_sample", []),
            title=rep.get("title") or f"{rep.get('service')} incident",
            description=rep.get("root_cause"),
            remediation_patch=rep.get("verified_fix"),
            anti_pattern=rep.get("anti_pattern"),
            comments=[{"author": "System", "text": f"Resolved fix: {rep.get('verified_fix')}", "timestamp": rep.get('closed_at')}],
            hindsight_runbook=f"Past fix on {rep.get('service')}: {rep.get('verified_fix')}. Anti-pattern: {rep.get('anti_pattern')}",
            is_recurring=True,
            environment_metadata=rep.get("environment_metadata", {})
        )
        TICKETS[tid] = t
    if past_reports:
        print(f"[*] Restored {len(TICKETS)} incident records from Supabase into active ticket memory.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_bank()
    seed_initial_tickets()
    restore_tickets_from_supabase()
    yield

app = FastAPI(title="Autonomous Incident Copilot", lifespan=lifespan)

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

def get_next_ticket_id() -> str:
    existing_nums = []
    for tid in TICKETS.keys():
        if tid.startswith("INC-"):
            try:
                existing_nums.append(int(tid.split("-")[1]))
            except ValueError:
                pass
    next_num = max(existing_nums) + 1 if existing_nums else 101
    return f"INC-{next_num}"

@app.post("/api/v1/alerts/trigger", status_code=201)
def trigger_alert(payload: AlertTriggerPayload):
    ticket_id = get_next_ticket_id()

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

    # Dynamic metadata extraction based on error type, service, and environment
    title = payload.title or f"{payload.error_type} in {payload.service}"
    description = payload.description or f"Failure detected during runtime on {payload.service}; transactions encountering error cascade."
    region = payload.region or DEFAULT_REGION
    degraded_pods = payload.degraded_pods or "Active instances impacted"
    error_spike = payload.error_spike or "Elevated error rate"
    detection_source = payload.detection_source or "COPILOT_WATCHER"
    blast_radius = payload.blast_radius or [f"{payload.service}:internal-worker", f"{payload.service}:egress"]
    remediation_patch = payload.remediation_patch
    anti_pattern = payload.anti_pattern
    anti_pattern_rationale = payload.anti_pattern_rationale
    env_meta = payload.environment_metadata or get_system_runtime_info()

    if not remediation_patch or not anti_pattern:
        gen_patch, gen_anti, gen_rationale = synthesize_remediation_and_anti_pattern(
            payload.service, payload.error_type, payload.raw_logs
        )
        if not remediation_patch:
            remediation_patch = gen_patch
        if not anti_pattern:
            anti_pattern = gen_anti
            anti_pattern_rationale = gen_rationale

    ticket = Ticket(
        id=ticket_id,
        service=payload.service,
        severity="P1",
        status="OPEN",
        created_at=now,
        raw_logs=payload.raw_logs,
        title=title,
        description=description,
        region=region,
        degraded_pods=degraded_pods,
        error_spike=error_spike,
        detection_source=detection_source,
        blast_radius=blast_radius,
        remediation_patch=remediation_patch,
        anti_pattern=anti_pattern,
        anti_pattern_rationale=anti_pattern_rationale,
        comments=[],
        hindsight_runbook=recalled_runbook or "First occurrence: No prior runbook found in Hindsight.",
        is_recurring=is_recurring,
        reduction_stats=None,
        agent_trace=agent_trace,
        environment_metadata=env_meta
    )
    TICKETS[ticket_id] = ticket

    port = get_env_var("PORT", "8000")
    return {
        "ticket_id": ticket.id,
        "service": ticket.service,
        "status": ticket.status,
        "is_recurring": is_recurring,
        "hindsight_injected_runbook": ticket.hindsight_runbook,
        "ide_quick_load": f"curl -s http://localhost:{port}/api/v1/tickets/{ticket.id}/context.md > .incident_context.md",
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

    extra_meta = TICKETS[ticket_id].environment_metadata if ticket_id in TICKETS else None
    post_mortem = run_idle_post_mortem(
        ticket_id, 
        service, 
        clean_logs, 
        clean_chat, 
        closed_at, 
        bank_id=BANK_ID, 
        extra_metadata=extra_meta
    )

    if ticket_id in TICKETS:
        ticket_obj = TICKETS[ticket_id]
        ticket_obj.final_post_mortem = post_mortem
        ticket_obj.agent_trace.append({
            "phase": "IDLE-PATH",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "Hindsight Memory Consolidated",
            "detail": f"Permanently stored verified fix and anti-pattern warning into Hindsight bank: {BANK_ID}"
        })

        # Persist full structured report into Supabase
        report_res = store_incident_report(
            ticket_id=ticket_obj.id,
            service=ticket_obj.service,
            title=ticket_obj.title or f"{ticket_obj.service} incident",
            root_cause=post_mortem.root_cause,
            verified_fix=post_mortem.verified_fix,
            anti_pattern=post_mortem.anti_pattern_warning,
            failed_attempts=post_mortem.failed_attempts,
            environment_metadata=ticket_obj.environment_metadata,
            raw_logs=ticket_obj.raw_logs,
            created_at=ticket_obj.created_at,
            closed_at=closed_at
        )
        ticket_obj.agent_trace.append({
            "phase": "IDLE-PATH",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "Supabase Report Saved",
            "detail": f"Stored complete post-mortem report into Supabase (persisted={report_res.get('persisted_to_supabase', False)})."
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
    budgeted_logs, budgeted_chat = apply_context_budget(clean_logs, clean_chat, max_log_lines=50, max_chat_messages=30)

    ticket.reduction_stats = {
        "raw_logs_count": len(ticket.raw_logs),
        "clean_logs_count": len(budgeted_logs),
        "raw_comments_count": len(ticket.comments),
        "clean_comments_count": len(budgeted_chat),
        "log_compression_pct": round((1.0 - (len(budgeted_logs) / max(len(ticket.raw_logs), 1))) * 100, 1)
    }

    # Queue Idle-Path synthesis worker asynchronously
    background_tasks.add_task(
        _async_idle_worker,
        ticket.id,
        ticket.service,
        budgeted_logs,
        budgeted_chat,
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

    env_block = ""
    if ticket.environment_metadata:
        env_lines = [f"- {k}: {v}" for k, v in ticket.environment_metadata.items()]
        env_block = f"\n## 2. Environment & System Metadata\n" + "\n".join(env_lines) + "\n"

    return f"""# INCIDENT CONTEXT: {ticket.id} ({ticket.service})
> Auto-generated by Incident Copilot at {ticket.created_at.isoformat()}Z.

## 1. Verified Failure Signature
- Service: {ticket.service}
- Status: {ticket.status}
- Severity: {ticket.severity}
{env_block}
## 3. Telemetry & Log Snippet
```text
{log_sample}
```

## 4. Institutional Runbook Memory (from Hindsight)
{ticket.hindsight_runbook}

## 5. Remediation Invariant
Any suggested fix must focus strictly on deployment or infrastructure configurations.
Do not modify core application business logic.
"""

@app.get("/api/v1/hindsight/memories")
def get_hindsight_memories():
    return {
        "bank_id": BANK_ID,
        "memories": get_all_memories()
    }

@app.get("/api/v1/reports")
def list_past_reports(limit: int = 50, service: Optional[str] = None):
    """Retrieves historical post-mortem incident reports stored in Supabase."""
    reports = get_past_reports(limit=limit, service=service)
    return {
        "count": len(reports),
        "reports": reports
    }

@app.get("/api/v1/realtime/status")
def get_realtime_app_status():
    """Polls real-time checkout-service metrics."""
    import requests
    try:
        res = requests.get(f"{CHECKOUT_BASE_URL}/metrics", timeout=1.0)
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
    try:
        requests.post(f"{CHECKOUT_BASE_URL}/admin/scale-pool", params={"new_pool_size": 10}, timeout=1.0)
    except Exception:
        pass
    return {"status": "demo_environment_reset"}
