"""CodeXRay API — configuration (PRD §14, §27, §28).

Secrets come from `services/api/.env` (Supabase) with a SQLite fallback
for offline dev and tests. `.env` is git-ignored — never commit it.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Supabase (fill real values in services/api/.env; placeholders until then).
# Server names first, Next.js NEXT_PUBLIC_* names as fallback so one copy
# of each value is enough.
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY") or os.getenv(
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", ""
)
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv(
    "SUPABASE_SECRET_KEY", ""
)


def _database_url() -> str:
    raw = os.getenv("DATABASE_URL", "")
    if not raw or "YOUR_REF" in raw:
        # Placeholders (or unset) → local SQLite so dev/tests keep working.
        return f"sqlite:///{BASE_DIR / 'codexray.db'}"
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


DATABASE_URL = _database_url()

# True when talking to Supabase's PgBouncer pooler (:6543), which requires
# a non-pooled (NullPool) client — pooled prepared statements break there.
USE_NULL_POOL = ":6543" in DATABASE_URL or "pooler" in DATABASE_URL

# Telemetry rate limit: max requests per API key per rolling minute.
TELEMETRY_RATE_LIMIT_PER_MIN = int(os.getenv("TELEMETRY_RATE_LIMIT_PER_MIN", "300"))

# Spans slower than this are flagged degraded (ms). PRD demo uses 2000ms timeouts.
SLOW_SPAN_MS = int(os.getenv("SLOW_SPAN_MS", "2000"))

# --- AI incident summary (Groq, OpenAI-compatible). Server-side only; the
# Groq key never leaves the backend. Empty => AI endpoints return 503 AI_DISABLED.
# Conversation is BYOK (user's own key) — see BYOK_* below.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
AI_TIMEOUT_S = float(os.getenv("AI_TIMEOUT_S", "12"))
AI_RATE_LIMIT_PER_MIN = int(os.getenv("AI_RATE_LIMIT_PER_MIN", "30"))
AI_MAX_SPANS = int(os.getenv("AI_MAX_SPANS", "30"))

# --- BYOK AI investigation (LiteLLM). The user's provider key is held in
# memory only, for a short TTL, keyed by an opaque connection id; it is never
# persisted, logged, or returned to the client. CodeXRay's budget pays for the
# automatic summary only — investigation runs on the user's own key.
BYOK_CONN_TTL_MIN = int(os.getenv("BYOK_CONN_TTL_MIN", "120"))
BYOK_MAX_HISTORY = int(os.getenv("BYOK_MAX_HISTORY", "12"))
BYOK_TIMEOUT_S = float(os.getenv("BYOK_TIMEOUT_S", "30"))
BYOK_MAX_TOKENS = int(os.getenv("BYOK_MAX_TOKENS", "800"))
BYOK_RATE_LIMIT_PER_MIN = int(os.getenv("BYOK_RATE_LIMIT_PER_MIN", "30"))

# --- One-click demo bootstrap. Creates a seeded demo project so first-time
# visitors reach the dashboard in one click. Set DEMO_SETUP=0 in production.
DEMO_SETUP = os.getenv("DEMO_SETUP", "1") == "1"

# --- Demo heartbeat: healthy-traffic pulses for demo projects so the graph,
# feed, and req/min stay alive during a walkthrough. DEMO_PULSE=0 disables.
DEMO_PULSE = os.getenv("DEMO_PULSE", "1") == "1"
