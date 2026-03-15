import requests
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
root = Path(__file__).resolve().parent.parent
load_dotenv(root / ".env")

API_BASE = "http://127.0.0.1:5000"
ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "Admin@1234")

def diag():
    print(f"Testing Admin Dashboard at {API_BASE}...")
    
    # 1. Login to get token
    r = requests.post(f"{API_BASE}/auth/login", json={
        "username": ADMIN_USER,
        "password": ADMIN_PASS
    })
    
    if r.status_code != 200:
        print(f"Login failed: {r.status_code} {r.text}")
        return
        
    token = r.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Test Dashboard
    print("\nCalling /admin/dashboard...")
    r = requests.get(f"{API_BASE}/admin/dashboard", headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print("Backend Error Output:")
        print(r.text)
    else:
        print("Dashboard call successful!")

    # 3. Test User List
    print("\nCalling /admin/users...")
    r = requests.get(f"{API_BASE}/admin/users", headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print("Backend Error Output:")
        print(r.text)

if __name__ == "__main__":
    diag()
