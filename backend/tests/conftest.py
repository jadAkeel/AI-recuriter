import os
import sys
from pathlib import Path


# Ensure `import app` works when running `pytest` from backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# Isolate tests from any local dev DB (e.g. backend/app.db).
TEST_DB_PATH = BACKEND_DIR / ".pytest_db.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}")

# Keep tests deterministic and independent from external services.
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("LLM_PROVIDER", "rule")

# Recreate SQLAlchemy engine so it picks up the env DATABASE_URL.
from app.core import db as _db  # noqa: E402

_db.reset_engine()


def pytest_sessionstart(session):
    # Best-effort cleanup so stale schema doesn't leak across runs.
    try:
        TEST_DB_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def pytest_sessionfinish(session, exitstatus):
    try:
        TEST_DB_PATH.unlink(missing_ok=True)
    except Exception:
        pass
