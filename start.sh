#!/usr/bin/env bash
# Start Incident Copilot in the background
PID_FILE="copilot.pid"
LOG_FILE="copilot.log"

if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "[!] Incident Copilot is already running with PID $(cat $PID_FILE)."
    exit 1
fi

echo "[*] Launching Incident Copilot server in background..."
nohup python3 -m uvicorn src.copilot.main:app --host 0.0.0.0 --port 8000 > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

sleep 1
if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "[+] Incident Copilot running in background (PID: $(cat $PID_FILE))."
    echo "[+] Web Dashboard: http://localhost:8000"
    echo "[+] Logs: tail -f $LOG_FILE"
else
    echo "[!] Failed to start. Check $LOG_FILE for errors."
fi
