import time
import os
import threading
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Production Checkout Service")

LOG_FILE = os.path.join(os.path.dirname(__file__), "checkout.log")

CONFIG = {
    "max_connections": 10,
    "active_connections": 0,
    "service_name": "checkout-service",
    "status": "healthy"
}
lock = threading.Lock()

def write_log(level: str, message: str):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    entry = f"{timestamp} {level} {message}\n"
    print(entry, end="")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)

class CheckoutRequest(BaseModel):
    user_id: str = "user-123"
    cart_total: float = 89.99

@app.on_event("startup")
def on_start():
    # Clear old log file
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} INFO checkout-service initialized on port 8050 (max_connections={CONFIG['max_connections']})\n")
    write_log("INFO", "Kubernetes pod checkout-service-7f8d9b-c4x9k ready for ingress")

@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": CONFIG["service_name"]}

@app.get("/metrics")
def get_metrics():
    with lock:
        return {
            "service": CONFIG["service_name"],
            "max_connections": CONFIG["max_connections"],
            "active_connections": CONFIG["active_connections"],
            "status": CONFIG["status"]
        }

@app.post("/checkout")
def process_checkout(req: CheckoutRequest):
    with lock:
        if CONFIG["active_connections"] >= CONFIG["max_connections"]:
            err_msg = f"ConnectionPool timeout: Max connections ({CONFIG['max_connections']}) exhausted under load"
            write_log("ERROR", err_msg)
            raise HTTPException(status_code=504, detail=err_msg)

        CONFIG["active_connections"] += 1

    write_log("INFO", f"Order initiated for user {req.user_id}, total=${req.cart_total}")

    try:
        # Simulate database work under load
        time.sleep(0.3)
        return {"status": "success", "order_id": f"ORD-{int(time.time() * 1000)}"}
    finally:
        with lock:
            CONFIG["active_connections"] = max(0, CONFIG["active_connections"] - 1)

@app.post("/admin/scale-pool")
def scale_connection_pool(new_pool_size: int = 50):
    """Simulates applying a Helm values patch to scale connection pool."""
    with lock:
        old_size = CONFIG["max_connections"]
        CONFIG["max_connections"] = new_pool_size
        CONFIG["status"] = "healthy"
    write_log("INFO", f"Helm patch applied: scaled max_connections from {old_size} to {new_pool_size}")
    return {"status": "pool_scaled", "old_pool": old_size, "new_pool": new_pool_size}

@app.post("/admin/restart")
def simulate_rolling_restart():
    """Simulates an on-call engineer restarting pods without changing pool limits."""
    write_log("WARN", "Rolling restart initiated on checkout-service pod replicas...")
    time.sleep(0.5)
    write_log("INFO", f"Pods restarted. Active pool limit remains constrained at {CONFIG['max_connections']}.")
    return {"status": "restarted", "max_connections": CONFIG["max_connections"]}
