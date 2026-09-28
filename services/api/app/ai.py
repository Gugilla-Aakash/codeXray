"""CodeXRay API — Groq-powered incident summary.

Generic by design: works for ANY project/trace, not just the demo seed.
Builds a compact, redacted context from the stored trace + deterministic
root-cause + replay ERROR actions, then calls Groq's OpenAI-compatible API.

The Groq key lives server-side only (config.GROQ_API_KEY). No new deps —
uses the existing httpx requirement.

Deeper, conversational investigation is BYOK and lives in `byok.py`; this
module only ever spends CodeXRay's own budget on the single cached summary.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from . import config
from .security import redact

SUMMARY_SYSTEM = (
    "You are CodeXRay, a precise distributed-systems debugging assistant. "
    "You receive a JSON incident context (trace spans, probable root cause with "
    "confidence and evidence signals, propagation path, replay error actions). "
    "Rules: use ONLY the provided context — never invent services, latencies, or errors. "
    "The root-cause confidence percentage is a deterministic engine score: "
    "quote it EXACTLY as given — never invent, recompute, or round percentages; "
    "if no confidence field is present, omit percentages entirely. "
    "Always label the cause as probable, never certain. "
    "Be concrete: name services, durations, and error messages from the context. "
    "Keep it under 150 words, 3 short sections: "
    "What failed / Probable root cause + evidence / Blast radius."
)

class AIError(Exception):
    """User-safe AI failure (message is safe to return as detail)."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def is_enabled() -> bool:
    return bool(config.GROQ_API_KEY)


def _truncate(s: Any, limit: int) -> Any:
    if isinstance(s, str) and len(s) > limit:
        return s[:limit] + "…"
    return s


def build_incident_context(
    trace: dict,
    spans: list[dict],
    root_cause: dict | None,
    error_actions: list[dict] | None = None,
) -> dict:
    """Compact redacted context for any incident/trace (any project)."""
    ordered = sorted(spans, key=lambda s: (s.get("timestamp", 0), s.get("span_id", "")))
    # Error spans first (most signal), then slowest — capped at AI_MAX_SPANS.
    errors = [s for s in ordered if (s.get("status") or "").lower() == "error"]
    rest = [s for s in ordered if (s.get("status") or "").lower() != "error"]
    rest.sort(key=lambda s: s.get("duration_ms", 0) or 0, reverse=True)
    picked = (errors + rest)[: max(1, config.AI_MAX_SPANS)]

    compact_spans = []
    for s in picked:
        err = s.get("error") or {}
        compact_spans.append(
            {
                "service": s.get("service"),
                "operation": _truncate(s.get("operation") or "", 120),
                "status": s.get("status"),
                "duration_ms": s.get("duration_ms"),
                "error_type": _truncate(err.get("type") or "", 80) if err else None,
                "error_message": _truncate(err.get("message") or "", 300) if err else None,
            }
        )
    ctx = {
        "trace_id": trace.get("trace_id"),
        "root_service": trace.get("root_service"),
        "trace_status": trace.get("status"),
        "trace_duration_ms": trace.get("duration_ms"),
        "span_count": len(spans),
        "spans_shown": len(compact_spans),
        "spans": compact_spans,
        "probable_root_cause": root_cause or None,
        "key_errors": [
            {"service": a.get("service"), "message": _truncate(a.get("message") or "", 200)}
            for a in (error_actions or [])
            if a.get("action") in ("ERROR", "RETRY")
        ][:10],
    }
    # Defense in depth: spans are already redacted at ingest, redact again
    # before leaving our network to a third-party LLM.
    return redact(ctx)


def summary_messages(ctx: dict) -> list[dict]:
    return [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": "Summarize this incident:\n" + _dump(ctx),
        },
    ]


def _dump(ctx: dict) -> str:
    import json

    return json.dumps(ctx, default=str)[:12000]


async def call_groq(messages: list[dict]) -> tuple[str, str]:
    """Return (text, model). Raises AIError with user-safe message."""
    if not is_enabled():
        raise AIError("AI not configured on server (GROQ_API_KEY missing)", status=503)
    url = config.GROQ_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=config.AI_TIMEOUT_S) as client:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                json={
                    "model": config.GROQ_MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 600,
                },
            )
    except httpx.TimeoutException:
        raise AIError("AI request timed out — try again") from None
    except httpx.HTTPError:
        raise AIError("AI provider unreachable — try again later") from None
    if r.status_code == 401:
        raise AIError("AI provider rejected the server key", status=502)
    if r.status_code == 429:
        raise AIError("AI rate limit hit — wait a minute and retry", status=502)
    if r.status_code >= 400:
        raise AIError(f"AI provider error ({r.status_code}) — try again", status=502)
    try:
        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        model = data.get("model", config.GROQ_MODEL)
    except (KeyError, IndexError, AttributeError, ValueError):
        raise AIError("AI returned an unreadable response — try again") from None
    if not text:
        raise AIError("AI returned an empty response — try again") from None
    return text, str(model)


def now() -> float:
    return time.time()
