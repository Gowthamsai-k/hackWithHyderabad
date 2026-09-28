# Autonomous Incident Copilot with Living Hindsight Memory

An autonomous, decoupled incident copilot that bridges real-time P1 outage triage with institutional post-mortem memory and agentic IDE context generation.

---

## 🚀 Key Architectural Innovations

1. **Decoupled Fast-Path / Idle-Path Engine:**
   - **Fast-Path (During Outage):** Sub-second deterministic ticket creation and read-only memory recall. Zero blocking LLM latency when engineers need fast, quiet answers.
   - **Idle-Path (Post-Incident):** Asynchronous Groq LLM synthesis kicks off only when a ticket is resolved, structuring technical facts and storing them in Hindsight memory.
2. **Negative Knowledge Retention (Anti-Pattern Warnings):**
   - Post-mortems capture not just what solved the problem, but **what failed** (e.g., *"Rolling restart re-triggered connection pool exhaustion"*), ensuring future engineers don't repeat the same dead ends.
3. **Passive Background Listener & In-Memory Ring Buffer:**
   - Continuously monitors raw log streams (`watcher.py`) with regex crash signature matching and fingerprint debouncing to prevent error storm alert floods.
4. **Information Reduction Funnel:**
   - Automatically collapses repetitive error cascades and strips conversational banter from triage channels before feeding into synthesis.
5. **Agentic Context Endpoint (`context.md`):**
   - Single-command context streaming for terminal and IDE agents (Claude Code, Cursor):
     ```bash
     curl -s http://localhost:8000/api/v1/tickets/INC-101/context.md > .incident_context.md
     ```
   - Eliminates repository pollution and dirty-tree CI failures.
6. **Full-Featured Incident CRM / Web Dashboard:**
   - Interactive dark-mode dashboard at `http://localhost:8000/` with live incident queues, real-time telemetry viewers, triage chat, one-click resolution synthesis, and simulated outage triggers.

---

## 📐 System Topology

```
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
│ 1. Sub-second Ticket Creation │               │ 1. Triggered on Ticket Close  │
│ 2. Recall Hindsight Runbook   │               │ 2. Compress Logs & Chat       │
│ 3. Serve `context.md` for IDE │               │ 3. LLM Extraction Pass (Groq) │
└───────────────┬───────────────┘               │ 4. Hindsight Retain & Reflect │
                │                               └───────────────────────────────┘
                ▼                                               ▲
┌───────────────────────────────┐                               │
│    INCIDENT CRM / WEB DASH    │                               │
│   (Team Chat & Remediation)   │                               │
│                               │                               │
│  "Tried rolling restart..."   │                               │
│  "Applied Helm pool patch..." │                               │
│  Status -> [ RESOLVED ] ──────┴───────────────────────────────┘
```

---


## 📁 Repository Structure

- [`schemas.py`](schemas.py) — Pydantic domain models for alerts, triage comments, post-mortem extractions, and tickets.
- [`filters.py`](filters.py) — Noise elimination regex and triage chatter filtering.
- [`watcher.py`](watcher.py) — In-memory ring buffer (100 lines) and fingerprint debouncer.
- [`hindsight_service.py`](hindsight_service.py) — Living memory bank initialization, multi-arm recall, and post-mortem retention (with resilient fallback).
- [`synthesizer.py`](synthesizer.py) — Post-incident LLM post-mortem synthesis (Groq with strict JSON output).
- [`main.py`](main.py) — FastAPI server exposing Fast-Path, Idle-Path, log ingestion, and Web Dashboard.
- [`static/dashboard.html`](static/dashboard.html) — Incident CRM and Web Dashboard.
- [`demo.py`](demo.py) — End-to-end simulation comparing novel incident baseline vs. recurring incident recall.
- [`tests/test_copilot.py`](tests/test_copilot.py) — Pytest test suite covering all modules and lifecycle flows.
- [`Dockerfile`](Dockerfile) & [`docker-compose.yml`](docker-compose.yml) — Containerized deployment.

---

## 🛠️ Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
```bash
cp .env.example .env
```
*(The system runs in resilient fallback mode if external keys are not provided).*

### 3. Run the Server & Access Web Dashboard
```bash
uvicorn main:app --port 8000 --reload
```
Open [http://localhost:8000](http://localhost:8000) in your browser to access the Incident CRM.

### 4. Execute the Hackathon Demo
In a separate terminal:
```bash
python demo.py
```

### 5. Run the Automated Test Suite
```bash
pytest -v
```