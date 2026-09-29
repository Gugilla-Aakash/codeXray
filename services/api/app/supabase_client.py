"""CodeXRay API — Supabase service-role client.

Server-side seam for Supabase platform features (health checks today;
Auth / Realtime / Storage tomorrow). The data path stays on SQLAlchemy —
this client never replaces it. Lazy singleton so tests and offline dev
work without keys configured.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from supabase import Client, create_client

from .config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    if not SUPABASE_URL or "YOUR_REF" in SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL is not configured (see services/api/.env)")
    if not SUPABASE_SERVICE_ROLE_KEY or "YOUR_" in SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured (see services/api/.env)")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def supabase_health() -> dict:
    """Read-only ping: can we reach the project? Returns {ok, latency_ms} or {ok: False, error}."""
    import time

    try:
        client = get_supabase()
        start = time.time()
        client.table("projects").select("id", count="exact").limit(0).execute()
        return {"ok": True, "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001 — full detail stays server-side
        # Never echo raw exception text to clients: it can carry URLs,
        # connection strings, or driver internals. Log it, return a stub.
        logger.warning("supabase health check failed: %s", exc)
        return {"ok": False, "error": "unavailable"}
