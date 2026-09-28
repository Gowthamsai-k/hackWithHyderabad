#!/usr/bin/env python3
import sys
import os
import subprocess
import requests

COPILOT_URL = os.getenv("COPILOT_URL", "http://127.0.0.1:8000")

def run_project(cmd_args: list):
    """
    Executes any fresh application (Java, Python, Go, Node, etc.).
    Automatically captures crashes, uncaught exceptions, and traces,
    routing them to the Copilot with zero configuration files needed.
    """
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

    if cmd_lower == "add":
        if len(sys.argv) < 4:
            print("Usage: copilot add <project-id> <log-path>")
            sys.exit(1)
        add_project(sys.argv[2], sys.argv[3])
    elif cmd_lower == "list":
        list_projects()
    elif cmd_lower == "watch":
        start_watcher()
    elif cmd_lower == "run":
        if len(sys.argv) < 3:
            print("Error: Missing command to run. Example: /hr run python3 main.py")
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
