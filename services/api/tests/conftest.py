"""Hermetic env for the API test suite.

pytest imports conftest.py BEFORE any test module, so blanking env vars here
guarantees app.config (which reads them at import) always sees the test
profile — even though test_ai.py imports `app.*` before test_api.py's own
env block would run. Without this, services/api/.env (real DATABASE_URL,
CODEXRAY_LICENSE_KEY, GROQ_API_KEY) leaks into the suite: the engine binds
to the live database and tests fail/hang against it.

Individual license tests then monkeypatch app.config.LICENSE_KEYS directly
to exercise the gated mode.
"""

from __future__ import annotations

import os

DB_PATH = "/tmp/opencode/codexray-test.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["GROQ_API_KEY"] = ""
os.environ["CODEXRAY_LICENSE_KEY"] = ""
os.environ["DEMO_PULSE"] = "0"
os.environ["DEMO_SETUP"] = "1"
