import time
import os
import requests
import concurrent.futures
from dotenv import load_dotenv

load_dotenv()

def get_env_var(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'\"")
    return val

HOST = get_env_var("CHECKOUT_SERVICE_HOST", "127.0.0.1")
PORT = get_env_var("CHECKOUT_SERVICE_PORT", "8050")
BASE_URL = f"http://{HOST}:{PORT}"

CHECKOUT_URL = f"{BASE_URL}/checkout"
ADMIN_SCALE_URL = f"{BASE_URL}/admin/scale-pool"
ADMIN_RESTART_URL = f"{BASE_URL}/admin/restart"

def send_single_checkout(user_id: int):
    try:
        res = requests.post(CHECKOUT_URL, json={"user_id": f"buyer-{user_id}", "cart_total": 49.99}, timeout=3.0)
        return res.status_code
    except Exception as e:
        return 504

def generate_traffic_surge(request_count: int = 25):
    """Spikes traffic exceeding the default pool size of 10 to trigger ConnectionPool timeout."""
    print(f"\n⚡ [CHAOS INJECTION] Sending traffic surge: {request_count} concurrent requests to /checkout...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=request_count) as executor:
        futures = [executor.submit(send_single_checkout, i) for i in range(request_count)]
        results = [f.result() for f in futures]

    successes = results.count(200)
    failures = results.count(504)
    print(f"[!] Ingress Surge Results: {successes} succeeded (200 OK), {failures} failed (504 ConnectionPool timeout)")
    return {"total": request_count, "200_ok": successes, "504_timeout": failures}

def apply_helm_patch(new_size: int = 50):
    print(f"\n🔧 [REMEDIATION] Applying Helm values patch: scaling pool to {new_size}...")
    res = requests.post(ADMIN_SCALE_URL, params={"new_pool_size": new_size})
    print(f"[+] Service response: {res.json()}")
    return res.json()

def apply_rolling_restart():
    print("\n🔄 [DEAD-END ATTEMPT] Simulating rolling restart on checkout-service...")
    res = requests.post(ADMIN_RESTART_URL)
    print(f"[+] Service response: {res.json()}")
    return res.json()

if __name__ == "__main__":
    generate_traffic_surge(25)
