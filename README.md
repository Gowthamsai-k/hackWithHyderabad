# 🛡️ Autonomous Incident Copilot with Living Hindsight Memory

An autonomous, decoupled SRE Incident Copilot that bridges real-time outage triage with institutional post-mortem memory, multi-project error tracking, and zero-pollution agentic IDE context generation.

---

## 🚀 Key Features & Architectural Innovations

1. **Decoupled Fast-Path vs. Idle-Path Engine:**
   - **Fast-Path (Outage Hot-Path):** Sub-10ms deterministic ticket creation and read-only memory recall. **Zero blocking LLM latency** when services crash.
   - **Idle-Path (Post-Incident Worker):** Asynchronous Groq LLM synthesis (`qwen/qwen3-32b`) kicks off when an incident is resolved to distill technical facts, verified fixes, and anti-pattern warnings into Hindsight memory.

2. **Negative Knowledge Retention (Anti-Pattern Warnings):**
   - Retains what **failed** in past traces (e.g. *"DO NOT perform rolling pod restarts; under active load, they re-trigger connection pool exhaustion and drop in-flight cart reservations"*), protecting on-call engineers from repeating historical mistakes.

3. **Multi-Project Error Tracking (Method 1 & Method 2):**
   - **Method 1 (`config/projects.yaml`):** Register any fresh project (Java, Python, Go, Node, etc.) with just an ID and log file path (`python3 copilot.py add <id> <log>`). The background watcher daemon attaches dynamically within 2 seconds without service restarts.
   - **Method 2 (`copilot.py run <cmd>`):** Universal CLI wrapper to run any app and automatically intercept uncaught exceptions and crashes.

4. **Dynamic Stack Trace & Unified-Diff Patch Synthesis:**
   - Automatically analyzes stack traces (Java `ArrayIndexOutOfBoundsException`, `NullPointerException`, Python `ZeroDivisionError`, `KeyError`, etc.) to synthesize:
     - The exact Unified-Diff remediation patch (`-` / `+` code diff).
     - Target file name and line numbers.
     - Specific operational anti-pattern warnings and rationales.

5. **Agentic Context Endpoint (`context.md`):**
   - Single-command context streaming for IDE/CLI AI agents (Claude Code, Cursor, Windsurf):
     ```bash
     curl -s http://localhost:8000/api/v1/tickets/INC-104/context.md | claude
     ```
   - Zero repository pollution, no temporary files, no dirty-tree CI build failures.

6. **Interactive SRE Incident CRM & Web Dashboard:**
   - Real-time dark-mode dashboard at `http://localhost:8000` matching SRE incident management workflows.
   - Live command queue, root cause stack trace viewer, remediation patch display, anti-pattern briefs, triage chat, and parsed `context.md` modal (with tabbed Preview/Raw view and zero modal overlap).

---

## 📐 System Topology

```text
                                [ MULTI-PROJECT LOG STREAMS ]
                                (Java, Python, Go, Node, etc.)
                                              │
                                              ▼
                                 [ Background Log Watcher ]
                                (Ring Buffer: last 100 lines)
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    │ [CRASH DETECTED]                                  │ [INCIDENT RESOLVED]
                    ▼                                                   ▼
┌───────────────────────────────────────┐               ┌───────────────────────────────────────┐
│        FAST-PATH: OUTAGE BUS          │               │        IDLE-PATH: ASYNC WORKER        │
├───────────────────────────────────────┤               ├───────────────────────────────────────┤
│ 1. Sub-second Ticket Creation         │               │ 1. Triggered on Ticket Resolution     │
│ 2. Read-Only Hindsight Recall         │               │ 2. Stratified Log & Chat Budgeting    │
│ 3. Unified-Diff & Anti-Pattern Gen    │               │ 3. Groq LLM Synthesis (qwen/qwen3-32b)│
│ 4. Serve `context.md` Endpoint        │               │ 4. Retain Memory & Reflect            │
└───────────────────┬───────────────────┘               └───────────────────────────────────────┘
                    │                                                   ▲
                    ▼                                                   │
┌───────────────────────────────────────┐                               │
│        INCIDENT CRM / WEB DASH        │                               │
│       (http://localhost:8000)         │                               │
│                                       │                               │
│  - Incident Command Queue             │                               │
│  - Stack Trace & Code Remediation     │                               │
│  - ⚠️ WHAT NOT TO DO Brief           │                               │
│  - Triage Chat & Ticket Resolution ───┴───────────────────────────────┘
```

---

## 📁 Project Directory Structure

```text
hackWithHyderabad/
├── src/                         # Core Python Application Package
│   └── copilot/
│       ├── __init__.py          # Package initialization
│       ├── main.py              # FastAPI server, Fast-Path API & endpoints
│       ├── schemas.py           # Pydantic models (Ticket, AlertPayload, etc.)
│       ├── filters.py           # Regex noise filter & context window budgeting
│       ├── synthesizer.py       # Post-mortem & Unified-Diff LLM synthesis
│       ├── hindsight_service.py # Hindsight memory bank integration & fallback
│       ├── watcher.py           # Passive log watcher & ring buffer
│       └── project_watcher.py   # Multi-project daemon & projects.yaml listener
├── config/                      # Centralized Configuration
│   └── projects.yaml            # Registered multi-project error tracking specs
├── docs/                        # Project Documentation & Architecture
│   ├── Prompt.md
│   ├── Names.md
│   ├── working_methid.txt
│   └── screen.png
├── static/                      # Web Dashboard Frontend
│   └── dashboard.html           # Incident CRM UI with marked.js context viewer
├── sample_service/              # Sample Services & Test Services
│   ├── checkout_app.py          # Real-time Checkout Microservice (port 8050)
│   ├── OrderBatchProcessor.java # Sample Java app throwing ArrayIndexOutOfBoundsException
│   ├── log_tailer.py            # Log tailer helper script
│   └── traffic_generator.py     # Real-time traffic surge simulator
├── tests/                       # Pytest Suite
│   └── test_copilot.py          # Automated verification test suite
├── copilot.py                   # Universal CLI Tool (add, list, watch, run)
├── Dockerfile                   # Production Docker definition
├── docker-compose.yml           # Compose orchestration config
├── pytest.ini                   # Pytest setup (pythonpath = src .)
├── requirements.txt             # Python dependencies
├── start.sh                     # Service launcher script
├── stop.sh                      # Service shutdown script
└── README.md                    # System documentation
```

---

## 🛠️ Quick Start Guide

### 1. Installation
Clone the repository and install required dependencies:
```bash
git clone https://github.com/Gowthamsai-k/hackWithHyderabad.git
cd hackWithHyderabad
pip install -r requirements.txt
```

### 2. Environment Configuration (Optional)
Create a `.env` file in the root directory:
```env
HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io
HINDSIGHT_API_KEY=your_hindsight_api_key_here
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=qwen/qwen3-32b
BANK_ID=incident-ops-bank
```
*(Note: If API keys are omitted, the system seamlessly operates in resilient offline fallback mode).*

### 3. Start the Incident Copilot
Launch the FastAPI server and background watchers using `start.sh`:
```bash
chmod +x start.sh stop.sh
./start.sh
```
Or start manually via uvicorn:
```bash
python3 -m uvicorn src.copilot.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **`http://localhost:8000`** in your browser to access the Incident CRM Dashboard.

---

## 🔍 Tracking Errors in Your Projects

### Method 1: Centralized Registry (`config/projects.yaml`)

Method 1 allows the Copilot to monitor any fresh project directory with **zero code modification**.

#### Step 1: Register your project
```bash
python3 copilot.py add my-app /path/to/my-app/app.log
```
Or append directly to [`config/projects.yaml`](file:///workspaces/hackWithHyderabad/config/projects.yaml):
```yaml
projects:
  - id: "my-app"
    log_file: "/path/to/my-app/app.log"
```

#### Step 2: Run the Background Watcher Daemon
```bash
python3 copilot.py watch
```
> The watcher daemon dynamically detects new projects in `config/projects.yaml` within 2 seconds without restarting.

#### Step 3: Run your project with log redirection
```bash
# Java App
java Main >> /path/to/my-app/app.log 2>&1

# Python App
python3 main.py >> /path/to/my-app/app.log 2>&1
```

---

### Method 2: Zero-Config CLI Wrapper (`copilot.py run`)

Run any application directly through the Copilot CLI wrapper to capture crashes instantly without touching any configuration files:

```bash
# Java Application
python3 copilot.py run java -cp . Main

# Python Application
python3 copilot.py run python3 main.py

# Node.js Application
python3 copilot.py run node index.js
```

---

## 💻 CLI Reference (`copilot.py`)

| Command | Usage | Description |
|---|---|---|
| **`add`** | `python3 copilot.py add <id> <log-path>` | Registers a new project in `config/projects.yaml` |
| **`list`** | `python3 copilot.py list` | Displays all monitored projects and log target readiness |
| **`watch`** | `python3 copilot.py watch` | Starts the multi-project background watcher daemon |
| **`run`** | `python3 copilot.py run <cmd>` | Executes an app and automatically intercepts uncaught crashes |

---

## 🤖 Agentic IDE Context Streaming (`context.md`)

When an incident ticket is generated (e.g. `INC-104`), your IDE or terminal AI agent (Claude Code, Cursor, Windsurf) can fetch full context with zero git pollution:

```bash
curl -s http://localhost:8000/api/v1/tickets/INC-104/context.md | claude
```

**Context Payload Includes:**
- Verified Failure Signature & Pod Metrics
- Telemetry & Sanitized Log Snippets
- Institutional Runbook Memory (from Hindsight)
- Specific Operational Invariants & Remediation Guidelines

---

## 🧪 Testing

Execute the automated test suite covering schemas, filters, watcher ring buffers, Hindsight memory fallback, synthesizer, and API endpoints:

```bash
pytest -v
```

---

## 🐳 Docker Deployment

### Run with Docker Compose
```bash
docker-compose up --build -d
```

### Run with Docker CLI
```bash
docker build -t incident-copilot .
docker run -d -p 8000:8000 --env-file .env incident-copilot
```

---

## 📜 License
MIT License. Created for Autonomous SRE Incident Management.