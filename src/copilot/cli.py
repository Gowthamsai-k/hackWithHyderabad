#!/usr/bin/env python3
import sys
import os
import subprocess
import requests
from dotenv import load_dotenv

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

COPILOT_URL = get_env_var("COPILOT_URL", f"http://{COPILOT_HOST}:{COPILOT_PORT}")

def print_help():
    help_text = """
================================================================================
AUTONOMOUS INCIDENT COPILOT -- HELP & COMMAND REFERENCE
================================================================================

[CLI COMMANDS]
  copilot add <project-id> <log-path>
      Registers a new project directory & log file in config/projects.yaml.
      Example: python3 copilot.py add my-app /var/log/my-app/app.log

  copilot list
      Lists all registered projects in config/projects.yaml and checks log readiness.

  copilot watch
      Starts the multi-project background watcher daemon (auto-attaches within 2s).

  copilot run <command>
      Executes any registered application command and intercepts crashes automatically.
      Example: python3 copilot.py run python3 main.py

  copilot run --file <target_file> -- <command>
      Executes a command with active Silent Fix Observer diff tracking on target file.
      Example: python3 copilot.py run --file processor.py -- python3 processor.py

  copilot memory inspect --service <name> [--dependency <name=version>]
      Inspects retained institutional runbooks and anti-patterns in Hindsight memory.

  copilot /help (or copilot help)
      Displays this command reference guide.

[REST API ENDPOINTS] (http://localhost:8000)
  GET  /                                Incident CRM Dashboard UI
  GET  /help                            API & CLI Command Reference
  POST /api/v1/alerts/trigger           Fast-Path ticket creation & runbook recall
  POST /api/v1/logs/ingest              Ingest log lines into passive ring buffer
  GET  /api/v1/tickets                  List active and resolved incident tickets
  GET  /api/v1/tickets/{id}             Fetch diagnostic ticket details & stack trace
  POST /api/v1/tickets/{id}/comment     Add triage observation or fix note to ticket
  POST /api/v1/tickets/{id}/resolve     Resolve ticket & trigger idle LLM post-mortem
  GET  /api/v1/tickets/{id}/context.md  Stream pure Markdown context for IDE agents
  GET  /api/v1/hindsight/memories       Inspect stored institutional memory bank
  GET  /api/v1/reports                  Fetch historical post-mortems from Supabase
  POST /api/v1/demo/reset               Reset demo environment & memory store
================================================================================
"""
    try:
        print(help_text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(help_text.encode('utf-8'))

def load_registered_projects() -> list:
    import yaml
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    config_path = os.path.join(base_dir, "config", "projects.yaml")
    if not os.path.exists(config_path):
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("projects", []) or []
    except Exception as e:
        print(f"[!] Warning reading config/projects.yaml: {e}")
        return []

def is_project_registered(target_ref: str = None) -> tuple[bool, str]:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True, "pytest-runner"

    cwd = os.path.abspath(os.getcwd())
    cwd_name = os.path.basename(cwd)
    projects = load_registered_projects()
    
    if not projects:
        return False, cwd_name

    target_abs = os.path.abspath(target_ref) if target_ref and os.path.exists(target_ref) else ""
    target_basename = os.path.basename(target_abs) if target_abs else (str(target_ref) if target_ref else "")

    for p in projects:
        p_id = str(p.get("id", "")).strip()
        p_service = str(p.get("service", "")).strip()
        log_file = str(p.get("log_file", "")).strip()
        log_abs = os.path.abspath(log_file) if log_file else ""
        log_dir = os.path.dirname(log_abs) if log_abs else ""

        if p_id and (p_id.lower() == cwd_name.lower() or p_id.lower() == target_basename.lower() or p_id.lower() == str(target_ref).lower()):
            return True, p_id
        if p_service and (p_service.lower() == cwd_name.lower() or p_service.lower() == target_basename.lower() or p_service.lower() == str(target_ref).lower()):
            return True, p_service

        if log_abs:
            if (cwd == log_dir or cwd.startswith(log_dir + os.sep) or log_dir.startswith(cwd + os.sep) or
                (target_abs and (target_abs.startswith(log_dir) or os.path.dirname(target_abs) == log_dir))):
                return True, p_id or p_service or cwd_name

    return False, cwd_name

def ensure_project_registered(target_ref: str = None) -> str:
    registered, proj_name = is_project_registered(target_ref)
    if not registered:
        cwd = os.path.abspath(os.getcwd())
        dir_name = os.path.basename(cwd)
        ref_display = target_ref or dir_name
        print("\n" + "=" * 70)
        print("❌ [Incident Copilot Error] UNREGISTERED PROJECT DIRECTORY!")
        print("=" * 70)
        print(f"Project directory/target '{ref_display}' is NOT registered in config/projects.yaml.")
        print(f"Current Working Directory: {cwd}")
        print("\nTo enable Incident Copilot monitoring, you MUST first register this project:")
        print(f"  python3 copilot.py add {dir_name} ./logs/{dir_name}.log\n")
        print("Or add your project directly into config/projects.yaml:")
        print("projects:")
        print(f"  - id: {dir_name}")
        print(f"    log_file: ./logs/{dir_name}.log")
        print("=" * 70 + "\n")
        sys.exit(1)
    return proj_name

def run_project(cmd_args: list):
    """
    Executes an application registered in config/projects.yaml.
    Automatically captures crashes, uncaught exceptions, and traces,
    routing them to the Copilot.
    """
    ensure_project_registered(cmd_args[0] if cmd_args else None)
    project_name = os.path.basename(os.getcwd())
    print(f"🚀 [Incident Copilot] Monitoring project '{project_name}'...")
    print(f"[*] Executing command: {' '.join(cmd_args)}\n")

    captured_logs = []
    has_error = False

    proc = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    for line in iter(proc.stdout.readline, ''):
        cleaned = line.rstrip()
        print(cleaned)
        captured_logs.append(cleaned)
        if any(err_kw in cleaned.lower() for err_kw in ["exception", "error", "fatal", "traceback", "panic", "outofbounds"]):
            has_error = True

    proc.stdout.close()
    return_code = proc.wait()

    if return_code != 0 or has_error:
        print("\n" + "=" * 65)
        print("🚨 [Incident Copilot] CRASH DETECTED! Intercepting trace...")
        print("=" * 65)

        error_type = "UnhandledCrash"
        for line in reversed(captured_logs):
            if "exception" in line.lower() or "error" in line.lower():
                error_type = line.split(":")[-1].strip() if ":" in line else line.strip()
                break

        try:
            payload = {
                "service": project_name,
                "error_type": error_type,
                "raw_logs": captured_logs[-30:] if len(captured_logs) > 30 else captured_logs,
                "title": f"Crash in {project_name}: {error_type}",
                "description": f"Application terminated with exit code {return_code}."
            }
            res = requests.post(f"{COPILOT_URL}/api/v1/alerts/trigger", json=payload, timeout=3.0)
            if res.status_code == 201:
                data = res.json()
                print(f"[+] Incident Created: {data['ticket_id']}")
                print(f"[+] Hindsight Memory: {data['hindsight_injected_runbook']}")
                print(f"\n🧠 Quick IDE Agent Load:")
                print(f"   $ {data['ide_quick_load']}")
                print(f"   (Pipe directly into Claude Code / Cursor to fix this crash!)")
        except Exception as e:
            print(f"[!] Could not notify Copilot server: {e}")

    sys.exit(return_code)

def add_project(project_id: str, log_file: str):
    import yaml
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    config_path = os.path.join(base_dir, "config", "projects.yaml")
    data = {"projects": []}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"projects": []}
            if "projects" not in data or data["projects"] is None:
                data["projects"] = []

    existing = [p for p in data["projects"] if p.get("id") == project_id]
    if existing:
        print(f"[!] Project '{project_id}' already exists in config/projects.yaml. Updating log_file.")
        existing[0]["log_file"] = log_file
    else:
        data["projects"].append({
            "id": project_id,
            "service": project_id,
            "log_file": log_file
        })
        print(f"[+] Added project '{project_id}' to config/projects.yaml.")

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    if not os.path.exists(log_file):
        with open(log_file, "a", encoding="utf-8") as f:
            pass
    print(f"[*] Log target initialized: {os.path.abspath(log_file)}")
    print(f"[*] Background watcher will dynamically attach to this project within 2 seconds.")

def list_projects():
    import yaml
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    config_path = os.path.join(base_dir, "config", "projects.yaml")
    if not os.path.exists(config_path):
        print("[-] No config/projects.yaml found.")
        return
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    projects = data.get("projects", [])
    print(f"\n📋 [Registered Projects in config/projects.yaml] ({len(projects)} total):")
    print(f"{'PROJECT ID':<25} {'LOG FILE':<40} {'STATUS'}")
    print("-" * 75)
    for p in projects:
        pid = p.get("id", "unknown")
        lf = p.get("log_file", "unknown")
        status = "Ready (log exists)" if os.path.exists(lf) else "Waiting (log not created yet)"
        print(f"{pid:<25} {lf:<40} {status}")
    print()

def start_watcher():
    from copilot.project_watcher import run_project_watcher_daemon
    run_project_watcher_daemon()

def main():
    if len(sys.argv) < 2:
        print("Autonomous Incident Copilot - Universal CLI Tool")
        print("\nDirect File & Command Execution:")
        print("  copilot main.py                       Run Python app & monitor crashes")
        print("  copilot OrderBatchProcessor.java      Compile/Run Java app & monitor crashes")
        print("  copilot app.js                        Run Node app & monitor crashes")
        print("  copilot run <command>                 Run any custom command")
        print("\nManagement Commands:")
        print("  copilot add <project-id> <log-path>   Register project in config/projects.yaml")
        print("  copilot list                          List all monitored projects")
        print("  copilot watch                         Start background watcher daemon")
        print("\nExamples:")
        print("  copilot main.py")
        print("  copilot OrderBatchProcessor.java")
        print("  copilot add my-app /var/log/my-app.log")
        sys.exit(1)

    cmd_lower = sys.argv[1].lower()

    if cmd_lower in ("help", "/help", "-h", "--help"):
        print_help()
        sys.exit(0)
    elif cmd_lower == "add":
        if len(sys.argv) < 4:
            print("Usage: copilot add <project-id> <log-path>")
            sys.exit(1)
        add_project(sys.argv[2], sys.argv[3])
    elif cmd_lower == "list":
        list_projects()
    elif cmd_lower == "watch":
        start_watcher()
    elif cmd_lower == "memory":
        # retrospect memory inspect --service checkout-service --dependency redis=7.2.4
        if len(sys.argv) >= 3 and sys.argv[2] == "inspect":
            from .hindsight_service import recall_memory
            service = "checkout-service"
            dependency = None
            for idx, arg in enumerate(sys.argv[3:]):
                if arg == "--service" and idx + 4 < len(sys.argv):
                    service = sys.argv[idx + 4]
                elif arg == "--dependency" and idx + 4 < len(sys.argv):
                    dependency = sys.argv[idx + 4]
            print(f"[*] Inspecting Hindsight memory for service '{service}' (dependency={dependency})...")
            recalled = recall_memory(service=service, error_type="crash", dependency=dependency)
            print("\n🧠 Recalled Runbooks:")
            print(recalled or "[-] No memories found matching criteria.")
        else:
            print("Usage: retrospect memory inspect --service <name> [--dependency <name=version>]")
    elif cmd_lower == "run":
        # Support both standard `retrospect run <cmd>` AND `retrospect run --file <target> -- <cmd>`
        if "--file" in sys.argv:
            from .diff_observer import run_observed_command
            file_idx = sys.argv.index("--file")
            target_file = sys.argv[file_idx + 1]
            ensure_project_registered(target_file)
            if "--" in sys.argv:
                cmd_start = sys.argv.index("--") + 1
                cmd_to_run = sys.argv[cmd_start:]
            else:
                cmd_to_run = sys.argv[file_idx + 2:]
            print(f"👁️ [Diff Observer Active] Observing '{target_file}' with command: {' '.join(cmd_to_run)}")
            code = run_observed_command(cmd_to_run, target_file)
            sys.exit(code)
        else:
            if len(sys.argv) < 3:
                print("Error: Missing command to run. Example: retrospect run python3 main.py")
                sys.exit(1)
            run_project(sys.argv[2:])
    else:
        target = sys.argv[1:]
        if len(target) == 1:
            file_arg = target[0]
            if file_arg.endswith(".py"):
                exec_cmd = [sys.executable, file_arg]
            elif file_arg.endswith(".java"):
                class_name = os.path.basename(file_arg)[:-5]
                dir_name = os.path.dirname(file_arg) or "."
                subprocess.run(["javac", file_arg], check=False)
                exec_cmd = ["java", "-cp", dir_name, class_name]
            elif file_arg.endswith(".js"):
                exec_cmd = ["node", file_arg]
            else:
                exec_cmd = target
        else:
            exec_cmd = target

        run_project(exec_cmd)

if __name__ == "__main__":
    main()
