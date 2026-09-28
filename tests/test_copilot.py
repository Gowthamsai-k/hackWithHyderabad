from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from copilot.schemas import AlertTriggerPayload, CommentPayload, PostMortemExtraction, Ticket
from copilot.filters import filter_logs, filter_chat
from copilot.watcher import BackgroundLogWatcher
from copilot import hindsight_service
from copilot import synthesizer
from copilot.main import app, TICKETS

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
    from copilot.filters import apply_context_budget
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
    test_bank = "incident-ops-test-bank"
    pm = synthesizer.run_idle_post_mortem(
        ticket_id="INC-UNITTEST",
        service="order-service",
        filtered_logs=["ERROR Postgres pool exhausted"],
        filtered_chat=[
            {"author": "Jane", "text": "restarted checkout pods but still crashing"},
            {"author": "Bob", "text": "patched helm pool max_connections to 80"}
        ],
        closed_at=datetime.now(timezone.utc),
        bank_id=test_bank
    )
    assert pm.root_cause
    assert len(pm.failed_attempts) > 0
    assert pm.verified_fix

    # Verify recall
    recalled = hindsight_service.recall_memory("order-service", "Postgres pool exhausted", bank_id=test_bank)
    assert recalled is not None
    assert "order-service" in recalled

    # Clean up test memory bank to prevent unit test leakage
    hindsight_service.reset_memory_bank()

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

def test_three_consecutive_incidents_adaptability():
    service_name = "cart-microservice"

    # --- Occurrence 1 ---
    res1 = client.post("/api/v1/alerts/trigger", json={
        "service": service_name,
        "error_type": "ConnectionPoolExhaustion",
        "raw_logs": ["ERROR CartRedis pool size 10 exhausted"]
    })
    t1_id = res1.json()["ticket_id"]
    client.post(f"/api/v1/tickets/{t1_id}/comment", json={"author": "Dev1", "text": "Scaled pool to 40 in helm patch_v1"})
    client.post(f"/api/v1/tickets/{t1_id}/resolve")

    # Retain post mortem manually in fallback store to ensure timestamp separation
    hindsight_service.retain_post_mortem(
        ticket_id=t1_id,
        service=service_name,
        post_mortem=PostMortemExtraction(
            root_cause="Pool size 10 exhausted",
            failed_attempts=["Pod restart"],
            verified_fix="Fix_V1: Scaled Redis pool to 40",
            anti_pattern_warning="Do not perform rolling restarts"
        ),
        closed_at=datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
    )

    # --- Occurrence 2 ---
    res2 = client.post("/api/v1/alerts/trigger", json={
        "service": service_name,
        "error_type": "ConnectionPoolExhaustion",
        "raw_logs": ["ERROR CartRedis pool size 40 exhausted under surge"]
    })
    t2_id = res2.json()["ticket_id"]
    client.post(f"/api/v1/tickets/{t2_id}/comment", json={"author": "Dev2", "text": "Fix_V2: Scaled Redis pool to 120 and set timeout to 60s"})
    client.post(f"/api/v1/tickets/{t2_id}/resolve")

    hindsight_service.retain_post_mortem(
        ticket_id=t2_id,
        service=service_name,
        post_mortem=PostMortemExtraction(
            root_cause="Pool size 40 exhausted under surge",
            failed_attempts=["Flush cache"],
            verified_fix="Fix_V2: Scaled Redis pool to 120 and set timeout to 60s",
            anti_pattern_warning="Do not lower timeout below 30s"
        ),
        closed_at=datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    )

    # --- Occurrence 3 ---
    res3 = client.post("/api/v1/alerts/trigger", json={
        "service": service_name,
        "error_type": "ConnectionPoolExhaustion",
        "raw_logs": ["ERROR CartRedis pool size exhausted again"]
    })
    t3_data = res3.json()
    t3_runbook = t3_data["hindsight_injected_runbook"]

    # Incident 3 MUST prioritize Incident 2's Fix_V2 over Incident 1's Fix_V1
    assert "Fix_V2: Scaled Redis pool to 120" in t3_runbook
    # Incident 2 should appear BEFORE Incident 1 in the recalled memory list
    v2_idx = t3_runbook.find("Fix_V2")
    v1_idx = t3_runbook.find("Fix_V1")
    assert v2_idx != -1
    if v1_idx != -1:
        assert v2_idx < v1_idx, "Incident 2's fix (Fix_V2) should appear before Incident 1's fix (Fix_V1)"

def test_first_and_second_occurrence_remediation_behavior():
    svc = "unique-test-service"
    
    # 1st Occurrence: First time
    patch1, anti1, _ = synthesizer.synthesize_remediation_and_anti_pattern(
        service=svc,
        error_type="SyntaxError",
        raw_logs=["SyntaxError: mismatched parenthesis"],
        recalled_runbook=None
    )
    assert "First-time incident observed" in patch1
    assert "No prior institutional memory" in patch1

    # 2nd Occurrence: Recalls 1st occurrence learnt outcome
    runbook_memory = "• 📌 Incident Reference: `INC-201` (`unique-test-service`)\n• ✅ Verified Fix: Corrected syntax by replacing mismatched bracket with round parenthesis"
    patch2, anti2, _ = synthesizer.synthesize_remediation_and_anti_pattern(
        service=svc,
        error_type="SyntaxError",
        raw_logs=["SyntaxError: mismatched parenthesis"],
        recalled_runbook=runbook_memory
    )
    assert "[Learnt Outcome from Incident History]" in patch2
    assert "Corrected syntax by replacing mismatched bracket with round parenthesis" in patch2


