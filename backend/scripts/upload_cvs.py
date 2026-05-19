#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import os
import time
from pathlib import Path

import httpx

API_BASE = "http://localhost:8000/api/v1"
API_URL = API_BASE + "/candidates"
CV_FOLDER = Path(__file__).parent / "cvs_to_upload"
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}
MAX_SIZE_MB = 15
MAX_RETRIES = 3
BACKOFF = 2


def file_sha256(path: Path) -> str:
    """
    Calculates the SHA-256 hash of a file.
    """
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_files(folder: Path) -> list[Path]:
    """
    Collects uploadable CV files from a folder.
    """
    files: list[Path] = []
    for ext in ALLOWED_EXTENSIONS:
        files.extend(folder.glob(f"*{ext}"))
        files.extend(folder.glob(f"*{ext.upper()}"))
    return sorted(set(files), key=lambda p: p.name.lower())


def validate_files(files: list[Path]) -> tuple[list[Path], list[str]]:
    """
    Separates valid CV files from rejected files.
    """
    accepted: list[Path] = []
    rejected: list[str] = []
    seen_hashes: set[str] = set()

    for path in files:
        ext = path.suffix.lower()
        size_mb = path.stat().st_size / (1024 * 1024)

        if ext not in ALLOWED_EXTENSIONS:
            rejected.append(f"{path.name}: unsupported extension")
            continue
        if size_mb > MAX_SIZE_MB:
            rejected.append(f"{path.name}: file too large ({size_mb:.1f} MB)")
            continue

        digest = file_sha256(path)
        if digest in seen_hashes:
            rejected.append(f"{path.name}: duplicate content")
            continue

        seen_hashes.add(digest)
        accepted.append(path)

    return accepted, rejected


def upload_file(
    client: httpx.Client,
    cv_path: Path,
    token: str | None,
) -> dict:
    """
    Uploads one CV file to the backend API.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    with cv_path.open("rb") as fh:
        response = client.post(
            API_URL,
            files={"file": (cv_path.name, fh)},
            params={"use_llm": "true"},
            headers=headers,
        )

    if response.status_code == 200:
        data = response.json()
        return {"status": "ok", "name": cv_path.name, "data": data}
    else:
        return {
            "status": "fail",
            "name": cv_path.name,
            "code": response.status_code,
            "detail": response.text[:200],
        }


def login(email: str, password: str) -> str | None:
    """
    Authenticates a user and returns access and refresh tokens.
    """
    try:
        resp = httpx.post(API_BASE + "/auth/login", json={"email": email, "password": password}, timeout=30)
        if resp.status_code == 200:
            return resp.json()["access_token"]
        print(f"  Login failed: {resp.status_code} {resp.text[:100]}")
    except Exception as exc:
        print(f"  Login error: {exc}")
    return None


def main() -> None:
    """
    Runs this script from the command line.
    """
    parser = argparse.ArgumentParser(description="Upload CVs to AI Recruiter API")
    parser.add_argument(
        "--token",
        default=os.getenv("API_TOKEN", ""),
        help="Bearer token for auth (or set API_TOKEN env var)",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Login with email (you'll be prompted for password)",
    )
    parser.add_argument(
        "--folder",
        default=str(CV_FOLDER),
        help="Folder containing CV files",
    )
    args = parser.parse_args()

    token = args.token or os.getenv("API_TOKEN", "")
    if not token and args.email:
        import getpass
        password = getpass.getpass("Password: ")
        token = login(args.email, password) or ""
        if not token:
            print("Login failed. Aborting.")
            return

    cv_folder = Path(args.folder)

    print("=" * 70)
    print("CV folder import (validated, one-by-one)")
    print("=" * 70)

    if not cv_folder.exists():
        print(f"Missing folder: {cv_folder}")
        print("Create it and copy CV files into it.")
        return

    files = collect_files(cv_folder)
    if not files:
        print(f"No CV files found in: {cv_folder}")
        return

    accepted, rejected = validate_files(files)
    print(f"Found: {len(files)} | Accepted: {len(accepted)} | Rejected: {len(rejected)}")
    for reason in rejected:
        print(f"  skip: {reason}")

    if not accepted:
        print("No valid files to upload.")
        return

    success = 0
    failed = 0

    with httpx.Client(timeout=180.0) as client:
        health = client.get(API_BASE + "/health")
        if health.status_code != 200:
            print("Backend is not healthy. Start API first.")
            return

        for idx, cv_path in enumerate(accepted, start=1):
            print(f"[{idx}/{len(accepted)}] {cv_path.name}")

            last_error = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = upload_file(client, cv_path, token)
                    if result["status"] == "ok":
                        data = result["data"]
                        print(
                            f"  OK: {data.get('full_name') or 'unknown'} | "
                            f"skills={len(data.get('skills', []))}"
                        )
                        success += 1
                        break
                    else:
                        if attempt < MAX_RETRIES and result["code"] in {429, 502, 503, 504}:
                            wait = BACKOFF ** attempt
                            print(f"  RETRY {attempt}/{MAX_RETRIES} (status={result['code']}, wait={wait}s)")
                            time.sleep(wait)
                            continue
                        print(f"  FAIL: {result['code']} | {result['detail']}")
                        failed += 1
                        break
                except Exception as exc:
                    last_error = exc
                    if attempt < MAX_RETRIES:
                        wait = BACKOFF ** attempt
                        print(f"  RETRY {attempt}/{MAX_RETRIES} (error={exc}, wait={wait}s)")
                        time.sleep(wait)
                        continue
                    print(f"  ERROR: {exc}")
                    failed += 1

    print("-" * 70)
    print(f"Done. success={success} failed={failed} total={len(accepted)}")


if __name__ == "__main__":
    main()
