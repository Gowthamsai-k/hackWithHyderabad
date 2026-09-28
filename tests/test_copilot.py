from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from schemas import AlertTriggerPayload, CommentPayload, PostMortemExtraction, Ticket
from filters import filter_logs, filter_chat
from watcher import BackgroundLogWatcher
import hindsight_service
import synthesizer
from main import app, TICKETS

client = TestClient(app)

def test_schemas():
    alert = AlertTriggerPayload(
        service="payment-service",
        error_type="DatabaseDeadlock",
        raw_logs=["ERROR deadlock detected"]
    )
    assert alert.service == "payment-service"

    comment = CommentPayload(author="Alice", text="Investigating database locks")
    assert comment.author == "Alice"

    pm = PostMortemExtraction(
        root_cause="Concurrent updates on unindexed row",
        failed_attempts=["Kill idle connections"],
        verified_fix="Added index on foreign key",
        anti_pattern_warning="Do not truncate transaction logs"
    )
    assert len(pm.failed_attempts) == 1
    assert "truncate" in pm.anti_pattern_warning

def test_filters():
    raw_logs = [
        "2026-09-28T10:00:00 INFO /healthz probe OK",
        "2026-09-28T10:00:01 INFO /metrics scraped",
        "2026-09-28T10:00:02 ERROR Redis::ConnectionTimeout uuid=123e4567-e89b-12d3-a456-426614174000",
        "2026-09-28T10:00:03 ERROR Redis::ConnectionTimeout uuid=123e4567-e89b-12d3-a456-426614174001",
        "2026-09-28T10:00:04 ERROR Redis::ConnectionTimeout uuid=123e4567-e89b-12d3-a456-426614174002"
    ]
    cleaned_logs = filter_logs(raw_logs)
    assert not any("/healthz" in l for l in cleaned_logs)
    assert any("collapsed" in l for l in cleaned_logs)

    comments = [
        {"author": "Dev", "text": "hey everyone, morning!"},
        {"author": "SRE", "text": "Initiated rolling restart on pod"},
        {"author": "Lead", "text": "Run `kubectl get pods -n prod`"}
    ]
    cleaned_chat = filter_chat(comments)
    assert len(cleaned_chat) == 2
    assert not any("morning" in c["text"] for c in cleaned_chat)

    # Test Stratified Windowing & Context Budget
    from filters import apply_context_budget
    long_logs = [f"2026-09-28 ERROR error number {i}" for i in range(120)]
    long_chat = [{"author": f"User{i}", "text": f"action step {i}"} for i in range(80)]
    budget_logs, budget_chat = apply_context_budget(long_logs, long_chat, max_log_lines=30, max_chat_messages=20)
    assert len(budget_logs) == 31  # 15 head + 1 omitted marker + 15 tail
    assert "omitted to fit context window" in budget_logs[15]
    assert len(budget_chat) == 21  # 10 head + 1 omitted marker + 10 tail

def test_watcher():
    watcher = BackgroundLogWatcher(buffer_size=5, debounce_window_sec=2.0)
    assert watcher.push_line("INFO healthy") is None
    err = watcher.push_line("ERROR ConnectionTimeout to redis")
    assert err is not None
    # Immediate repeat debounced
    assert watcher.push_line("ERROR ConnectionTimeout to redis") is None
    assert len(watcher.get_context_slice()) == 3

def test_hindsight_and_synthesizer():
    pm = synthesizer.run_idle_post_mortem(
        ticket_id="INC-UNITTEST",
        service="order-service",
        filtered_logs=["ERROR Postgres pool exhausted"],
        filtered_chat=[
            {"author": "Jane", "text": "restarted checkout pods but still crashing"},
            {"author": "Bob", "text": "patched helm pool max_connections to 80"}
        ],
        closed_at=datetime.now(timezone.utc)
    )
    assert pm.root_cause
    assert len(pm.failed_attempts) > 0
    assert pm.verified_fix

    # Verify recall
    recalled = hindsight_service.recall_memory("order-service", "Postgres pool exhausted")
    assert recalled is not None
    assert "order-service" in recalled

def test_api_full_lifecycle():
    # 1. Trigger Alert
    res = client.post("/api/v1/alerts/trigger", json={
        "service": "auth-service",
        "error_type": "JWT::InvalidSignature",
        "raw_logs": ["2026-09-28 ERROR JWT::InvalidSignature: secret expired"]
    })
    assert res.status_code == 201
    data = res.json()
    ticket_id = data["ticket_id"]
    assert "INC-" in ticket_id
    assert data["status"] == "OPEN"

    # 2. Add Comment
    res_comment = client.post(f"/api/v1/tickets/{ticket_id}/comment", json={
        "author": "SecOps",
        "text": "Rotated secret key via vault patch"
    })
    assert res_comment.status_code == 200

    # 3. Retrieve Context Markdown
    res_md = client.get(f"/api/v1/tickets/{ticket_id}/context.md")
    assert res_md.status_code == 200
    assert f"# INCIDENT CONTEXT: {ticket_id}" in res_md.text

    # 4. Resolve Ticket
    res_resolve = client.post(f"/api/v1/tickets/{ticket_id}/resolve")
    assert res_resolve.status_code == 200
    assert res_resolve.json()["status"] == "ticket_resolved"

    # 5. Check Log Ingestion endpoint
    res_ingest = client.post("/api/v1/logs/ingest", json={
        "service": "auth-service",
        "log_line": "INFO standard auth trace"
    })
    assert res_ingest.status_code == 200
    assert res_ingest.json()["status"] == "buffered"
