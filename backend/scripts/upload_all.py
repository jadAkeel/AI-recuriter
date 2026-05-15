"""
Upload all CVs with Ollama for matching.
"""
import httpx, sys, time, subprocess
from pathlib import Path

PORT = 8000
BASE = f"http://localhost:{PORT}/api/v1"
CV_FOLDER = Path(__file__).parent / "cvs_to_upload"

# Start server
proc = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', str(PORT), '--log-level', 'info'],
    cwd=str(Path(__file__).parent),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print(f'Server PID: {proc.pid}')
time.sleep(6)

try:
    r = httpx.get(f"{BASE}/health", timeout=5)
    print(f'Health: {r.json()}')

    # Register + login
    email = "jadakeel05@gmail.com"
    password = "123"
    r = httpx.post(f"{BASE}/auth/register", json={"email": email, "password": password, "full_name": "Admin"}, timeout=10)
    if r.status_code == 409:
        print("User already exists")

    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=10)
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Logged in")

    # Upload CVs
    files = sorted(CV_FOLDER.glob("*.pdf"))
    success, failed = 0, 0
    for i, f in enumerate(files, 1):
        print(f'[{i}/{len(files)}] {f.name}...', end=' ', flush=True)
        try:
            with open(f, 'rb') as fp:
                r = httpx.post(f"{BASE}/candidates", files={"file": (f.name, fp)}, headers=headers, timeout=300)
            if r.status_code == 200:
                d = r.json()
                print(f'OK: {d.get("full_name","?")[:20]} | skills={len(d.get("skills",[]))}')
                success += 1
            else:
                print(f'FAIL: {r.status_code} {r.text[:80]}')
                failed += 1
        except Exception as e:
            print(f'ERROR: {e}')
            failed += 1
        time.sleep(1)

    print(f'\nDone: {success} success, {failed} failed out of {len(files)}')
    print(f'Server still running on http://localhost:{PORT}')

    # Keep server running
    proc.wait()
except KeyboardInterrupt:
    print("\nStopping...")
finally:
    proc.terminate()
