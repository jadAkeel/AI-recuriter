"""
Delete all candidates, regenerate CVs with Lebanese names, upload fresh.
"""
import getpass
import os
import httpx, sys, time, subprocess
from pathlib import Path

PORT = 8000
BASE = f"http://localhost:{PORT}/api/v1"
BACKEND_DIR = Path(__file__).resolve().parents[1]
CV_FOLDER = BACKEND_DIR / "cvs_to_upload"

# Start server
proc = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', str(PORT), '--log-level', 'info'],
    cwd=str(BACKEND_DIR),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print(f'Server PID: {proc.pid}')
time.sleep(6)

try:
    r = httpx.get(f"{BASE}/health", timeout=5)
    print(f'Health: {r.json()}')

    # Login
    email = os.environ.get("AI_RECRUITER_ADMIN_EMAIL") or input("Admin email: ").strip()
    password = os.environ.get("AI_RECRUITER_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=10)
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Logged in")

    # Step 1: Delete all existing candidates
    print("\n=== Deleting all candidates ===")
    r = httpx.delete(f"{BASE}/candidates", headers=headers, timeout=30)
    print(f'Delete response: {r.status_code} {r.text[:200]}')

    # Step 2: Clean old CV PDFs
    print("\n=== Cleaning old CV PDFs ===")
    if CV_FOLDER.exists():
        for f in CV_FOLDER.glob("*.pdf"):
            f.unlink()
        print(f"Cleaned {CV_FOLDER}")
    else:
        CV_FOLDER.mkdir(parents=True)

    # Step 3: Generate new CVs with Lebanese names
    print("\n=== Generating new CVs with Lebanese names ===")
    import importlib.util, runpy
    spec = importlib.util.spec_from_file_location("generate_cs_cvs", Path(__file__).parent / "generate_cs_cvs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()

    # Step 4: Upload new CVs
    print("\n=== Uploading new CVs ===")
    files = sorted(CV_FOLDER.glob("*.pdf"))
    success, failed = 0, 0
    for i, f in enumerate(files, 1):
        print(f'[{i}/{len(files)}] {f.name}...', end=' ', flush=True)
        try:
            with open(f, 'rb') as fp:
                r = httpx.post(f"{BASE}/candidates", files={"file": (f.name, fp)}, headers=headers, timeout=300)
            if r.status_code == 200:
                d = r.json()
                print(f'OK: {d.get("full_name","?")[:25]} | skills={len(d.get("skills",[]))}')
                success += 1
            else:
                print(f'FAIL: {r.status_code} {r.text[:80]}')
                failed += 1
        except Exception as e:
            print(f'ERROR: {e}')
            failed += 1
        time.sleep(0.5)

    print(f'\nDone: {success} success, {failed} failed out of {len(files)}')
    print(f'Server still running on http://localhost:{PORT}')

    proc.wait()
except KeyboardInterrupt:
    print("\nStopping...")
finally:
    proc.terminate()
