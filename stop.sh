#!/usr/bin/env bash
# Stop Incident Copilot background process
PID_FILE="copilot.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "[!] No copilot.pid file found. Service may not be running."
    exit 1
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    echo "[*] Stopping Incident Copilot (PID: $PID)..."
    kill "$PID"
    rm -f "$PID_FILE"
    echo "[+] Service stopped successfully."
else
    echo "[!] Process $PID not found. Removing stale PID file."
    rm -f "$PID_FILE"
fi
