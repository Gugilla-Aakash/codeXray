"""CodeXRay API — BYOK AI investigation (LiteLLM).

The automatic incident summary in `ai.py` spends CodeXRay's own Groq budget.
This module is deliberately the opposite: the user brings their own provider
key, picks a provider + model, and gets a streaming conversational debugging
session. The key is used only to make the outbound call — it is never
persisted, logged, or returned to the client.

Every provider call goes through ``litellm`` (one abstraction), so adding a
provider is a registry entry, not a new call site. Routing is driven by the
selected provider via an explicit LiteLLM provider prefix, which is what
guarantees, for example, that Kimi/Moonshot traffic never lands on OpenAI.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import litellm

from . import config
from .security import BaseUrlError, redact, validate_base_url

# litellm must never emit request/response bodies or keys to its logger.
litellm.suppress_debug_info = True
litellm.set_verbose = False  # type: ignore[attr-defined]

log = logging.getLogger("codexray.byok")


# --------------------------------------------------------------------------
# Provider registry — provider selection drives routing.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    litellm_prefix: str          # explicit LiteLLM provider namespace
    default_base_url: str | None
    base_url_editable: bool
    requires_base_url: bool
    models: tuple[str, ...]
    note: str = ""


PROVIDERS: dict[str, Provider] = {
    "openai": Provider(
        id="openai",
        label="OpenAI",
        litellm_prefix="openai",
        default_base_url=None,
        base_url_editable=True,
        requires_base_url=False,
        models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o4-mini"),
    ),
    "groq": Provider(
        id="groq",
        label="Groq",
        litellm_prefix="groq",
        default_base_url=None,
        base_url_editable=False,
        requires_base_url=False,
        models=(
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "moonshotai/kimi-k2-instruct",
            "qwen/qwen3-32b",
        ),
        note="Ultra-fast inference. Runs on your Groq key — billed by Groq.",
    ),
    "anthropic": Provider(
        id="anthropic",
        label="Anthropic",
        litellm_prefix="anthropic",
        default_base_url=None,
        base_url_editable=False,
        requires_base_url=False,
        models=(
            "claude-3-5-haiku-latest",
            "claude-3-7-sonnet-latest",
            "claude-sonnet-4-20250514",
        ),
    ),
    "gemini": Provider(
        id="gemini",
        label="Google Gemini",
        litellm_prefix="gemini",
        default_base_url=None,
        base_url_editable=False,
        requires_base_url=False,
        # gemini-1.5-* were retired by Google (404 NOT_FOUND) — never offer them.
        models=("gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite"),
    ),
    "moonshot": Provider(
        id="moonshot",
        label="Moonshot / Kimi",
        litellm_prefix="moonshot",
        default_base_url="https://api.moonshot.ai/v1",
        base_url_editable=True,
        requires_base_url=False,
        models=("kimi-k2-0711-preview", "moonshot-v1-8k", "moonshot-v1-32k"),
        note="OpenAI-compatible; routed via the moonshot provider, never openai.",
    ),
    "openrouter": Provider(
        id="openrouter",
        label="OpenRouter",
        litellm_prefix="openrouter",
        default_base_url=None,
        base_url_editable=False,
        requires_base_url=False,
        models=(
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o-mini",
            "google/gemini-flash-1.5",
        ),
    ),
    "custom": Provider(
        id="custom",
        label="Custom (OpenAI-compatible)",
        litellm_prefix="openai",
        default_base_url=None,
        base_url_editable=True,
        requires_base_url=True,
        models=(),
        note="Any OpenAI-compatible endpoint. Base URL is required.",
    ),
}


def providers_public() -> list[dict]:
    """Safe provider metadata for the frontend. Never includes secrets."""
    return [
        {
            "id": p.id,
            "label": p.label,
            "models": list(p.models),
            "baseUrlEditable": p.base_url_editable,
            "requiresBaseUrl": p.requires_base_url,
            "defaultBaseUrl": p.default_base_url,
            "note": p.note,
        }
        for p in PROVIDERS.values()
    ]


def litellm_model(provider_id: str, model: str) -> str:
    """Prefix the model with the selected provider's LiteLLM namespace.

    The provider — not the key, not the base URL — decides the route, so a
    Moonshot/Kimi model can never be dispatched as an OpenAI model. A pasted
    id that already carries the same namespace is left intact.
    """
    p = PROVIDERS[provider_id]
    m = (model or "").strip()
    if m == p.litellm_prefix or m.startswith(p.litellm_prefix + "/"):
        return m
    return f"{p.litellm_prefix}/{m}"


def _resolve_base_url(provider_id: str, base_url: str | None) -> str | None:
    p = PROVIDERS[provider_id]
    user = (base_url or "").strip()
    chosen = user or p.default_base_url
    if p.requires_base_url and not chosen:
        raise ByokError("invalid_config", "A base URL is required for this provider.", 400)
    if not p.base_url_editable and user:
        raise ByokError("invalid_config", "This provider does not accept a custom base URL.", 400)
    if user:
        # SSRF guard: only user-controlled URLs are untrusted; our shipped
        # defaults are constants. Runs before LiteLLM opens any socket.
        try:
            validate_base_url(user)
        except BaseUrlError as exc:
            raise ByokError("invalid_base_url", str(exc), 400) from None
    return chosen


def _connection_spec(provider_id: str, model: str, base_url: str | None) -> tuple[str, str | None]:
    if provider_id not in PROVIDERS:
        raise ByokError("invalid_config", "Unknown provider.", 400)
    if not (model or "").strip():
        raise ByokError("invalid_config", "A model is required.", 400)
    return litellm_model(provider_id, model), _resolve_base_url(provider_id, base_url)


# --------------------------------------------------------------------------
# Errors — provider-neutral, never leak keys or raw provider traces.
# --------------------------------------------------------------------------

class ByokError(Exception):
    """User-safe investigation failure. Message is safe to return as detail."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


def _normalize_error(e: Exception) -> ByokError:
    name = type(e).__name__
    msg = str(e).lower()
    if any(k in msg for k in ("insufficient", "quota", "credit", "billing", "payment")):
        return ByokError("insufficient_credits", "Insufficient provider credits or quota.", 402)
    if isinstance(e, litellm.AuthenticationError) or "authentication" in name.lower():
        return ByokError("auth_failed", "Authentication failed — check your API key.", 401)
    if isinstance(e, litellm.RateLimitError):
        return ByokError("rate_limited", "Provider rate limit — try again shortly.", 429)
    if isinstance(e, litellm.NotFoundError):
        return ByokError("model_unavailable", "Model unavailable — check the model name.", 404)
    if isinstance(e, litellm.BadRequestError):
        return ByokError("invalid_config", "Invalid provider configuration, model, or base URL.", 400)
    # NOTE: litellm.Timeout subclasses APIConnectionError, so check it first.
    if isinstance(e, litellm.Timeout):
        return ByokError("timeout", "Provider timed out.", 504)
    if isinstance(e, litellm.APIConnectionError):
        return ByokError("network_error", "Network error — could not reach the provider.", 502)
    if isinstance(e, litellm.APIError):
        return ByokError("provider_error", "Provider returned an error — try again.", 502)
    # Base URL / DNS / TLS problems surface as generic connection errors.
    if any(k in msg for k in ("connection", "connect", "resolve", "ssl", "certificate", "invalid url", "nodename")):
        return ByokError("network_error", "Could not reach the provider endpoint — check the base URL.", 502)
    return ByokError("provider_error", "Provider request failed — try again.", 502)


# --------------------------------------------------------------------------
# Connection store — opaque id, in-memory only, short TTL.
# --------------------------------------------------------------------------

@dataclass
class Connection:
    id: str
    project_id: str
    provider: str
    model: str
    base_url: str | None
    created_at: float
    # repr=False so the key can never leak via incidental logging/printing.
    api_key: str = field(repr=False, default="")
    last_used: float = 0.0

    def public(self) -> dict:
        return {
            "connectionId": self.id,
            "provider": self.provider,
            "model": self.model,
            "baseUrl": self.base_url,
        }


class ConnectionStore:
    """Holds user keys in process memory only, scoped by project + TTL."""

    def __init__(self, ttl_s: float) -> None:
        self.ttl_s = ttl_s
        self._items: dict[str, Connection] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        for cid in [c for c, v in self._items.items() if now - v.last_used > self.ttl_s]:
            self._items.pop(cid, None)

    def create(
        self,
        project_id: str,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None,
    ) -> Connection:
        if not (api_key or "").strip():
            raise ByokError("invalid_config", "An API key is required.", 400)
        now = time.time()
        conn = Connection(
            id="conn_" + secrets.token_urlsafe(18),
            project_id=project_id,
            provider=provider,
            model=model,
            base_url=base_url,
            created_at=now,
            api_key=api_key.strip(),
            last_used=now,
        )
        with self._lock:
            self._prune(now)
            self._items[conn.id] = conn
        return conn

    def get(self, project_id: str, connection_id: str) -> Connection:
        now = time.time()
        with self._lock:
            self._prune(now)
            conn = self._items.get(connection_id)
        if conn is None or conn.project_id != project_id:
            raise ByokError("connection_not_found", "Connection not found or expired.", 404)
        conn.last_used = now
        return conn

    def drop(self, project_id: str, connection_id: str) -> None:
        with self._lock:
            conn = self._items.get(connection_id)
            if conn is not None and conn.project_id == project_id:
                self._items.pop(connection_id, None)


connections = ConnectionStore(ttl_s=config.BYOK_CONN_TTL_MIN * 60)


# --------------------------------------------------------------------------
# Prompting + context.
# --------------------------------------------------------------------------

INVESTIGATION_SYSTEM = (
    "You are CodeXRay's investigation assistant. You are given a structured "
    "JSON 'InvestigationContext' about ONE incident and asked questions by a "
    "developer. Rules: ground every claim in the provided context — never "
    "invent services, timings, errors, or code. If something is not in the "
    "context, say so plainly. Always label diagnoses as probable, not certain. "
    "Cite concrete service names, operations, durations and error messages. "
    "Be concise: prefer short paragraphs or bullets. When asked how to fix, "
    "give specific, testable steps."
)


def build_investigation_context(
    incident: dict,
    trace: dict,
    spans: list[dict],
    ai_summary: str | None = None,
) -> dict:
    """Structured, redacted context for one incident (BYOK investigation)."""
    ordered = sorted(spans, key=lambda s: (s.get("timestamp", 0), s.get("span_id", "")))
    root = next((s for s in ordered if not s.get("parent_span_id")), ordered[0] if ordered else None)

    def _span(s: dict) -> dict:
        err = s.get("error") or {}
        return {
            "service": s.get("service"),
            "operation": s.get("operation"),
            "status": s.get("status"),
            "durationMs": s.get("duration_ms"),
            "errorType": (err.get("type") or None) if err else None,
            "errorMessage": (err.get("message") or None) if err else None,
            "offsetMs": (
                round((s.get("timestamp", 0) - (root or {}).get("timestamp", 0)) * 1000, 1)
                if root
                else None
            ),
        }

    error_spans = [s for s in ordered if (s.get("status") or "").lower() == "error"]
    stack_trace = None
    if error_spans:
        deepest = max(error_spans, key=lambda s: (s.get("timestamp", 0)))
        stack_trace = ((deepest.get("error") or {}).get("message")) or None

    request = None
    if root:
        req = root.get("request") or {}
        resp = root.get("response") or {}
        if req or resp:
            request = {
                "method": req.get("method"),
                "path": req.get("path"),
                "statusCode": resp.get("status_code") or resp.get("statusCode"),
                "duration": root.get("duration_ms"),
            }

    dependencies: set[str] = set()
    parent_service = {s.get("span_id"): s.get("service") for s in ordered}
    for s in ordered:
        pid = s.get("parent_span_id")
        if pid and pid in parent_service and parent_service[pid] != s.get("service"):
            dependencies.add(f"{parent_service[pid]} -> {s.get('service')}")

    span_cap = max(1, config.AI_MAX_SPANS)
    services = incident.get("affected_services") or sorted(
        {s.get("service") for s in ordered if s.get("service")}
    )

    ctx = {
        "incidentId": incident.get("incident_id"),
        "title": incident.get("title"),
        "severity": incident.get("severity"),
        "status": incident.get("status"),
        "rootCause": incident.get("root_cause") or None,
        "summary": ai_summary or None,
        "request": request,
        "stackTrace": stack_trace,
        "timeline": [_span(s) for s in ordered[:span_cap]],
        "spansShown": min(len(ordered), span_cap),
        "spanCount": len(ordered),
        "services": services,
        "dependencies": sorted(dependencies),
        "relevantCode": [],
        "metadata": {
            "trace_id": trace.get("trace_id"),
            "root_service": trace.get("root_service"),
            "trace_status": trace.get("status"),
            "trace_duration_ms": trace.get("duration_ms"),
        },
    }
    # Defense in depth: ingest already redacts, redact again before the data
    # leaves our network to a user-chosen third-party provider.
    return redact(ctx)


def _dump(ctx: dict) -> str:
    return json.dumps(ctx, default=str)[:16000]


def investigation_messages(
    ctx: dict, question: str, history: list[dict] | None = None
) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": INVESTIGATION_SYSTEM}]
    msgs.append({"role": "user", "content": "InvestigationContext:\n" + _dump(ctx)})
    for h in (history or [])[-config.BYOK_MAX_HISTORY:]:
        role = h.get("role") if h.get("role") in ("user", "assistant") else "user"
        content = str(h.get("content", ""))[:4000]
        if content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": question.strip()})
    return msgs


# --------------------------------------------------------------------------
# Provider calls (one abstraction).
# --------------------------------------------------------------------------

def _kwargs(conn: Connection) -> dict:
    model_id, base_url = _connection_spec(conn.provider, conn.model, conn.base_url)
    kw: dict[str, Any] = {
        "model": model_id,
        "api_key": conn.api_key,
        "timeout": config.BYOK_TIMEOUT_S,
    }
    if base_url:
        kw["api_base"] = base_url
    return kw


def _log(event: str, conn: Connection, **safe: Any) -> None:
    """Metadata-only logging. Never includes the key or prompt/context bodies."""
    log.info(
        json.dumps(
            {
                "event": event,
                "provider": conn.provider,
                "model": conn.model,
                "connection_id": conn.id,
                **safe,
            }
        )
    )


async def test_connection(
    provider: str, model: str, api_key: str, base_url: str | None
) -> dict:
    """Minimal, inexpensive round-trip to validate provider/model/key/base URL."""
    model_id, resolved_base = _connection_spec(provider, model, base_url)
    started = time.time()
    try:
        resp = await litellm.acompletion(
            model=model_id,
            api_key=api_key.strip(),
            api_base=resolved_base,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=1,
            temperature=0,
            timeout=config.BYOK_TIMEOUT_S,
        )
        used_model = getattr(resp, "model", None) or model
    except ByokError:
        raise
    except Exception as e:  # noqa: BLE001 — normalized below, never re-raised raw
        raise _normalize_error(e) from None
    log.info(
        json.dumps(
            {
                "event": "byok.test",
                "provider": provider,
                "model": model,
                "status": "ok",
                "duration_ms": round((time.time() - started) * 1000, 1),
            }
        )
    )
    return {"success": True, "provider": provider, "model": str(used_model), "baseUrl": resolved_base}


async def complete(
    conn: Connection,
    ctx: dict,
    question: str,
    history: list[dict] | None = None,
) -> dict:
    started = time.time()
    try:
        resp = await litellm.acompletion(
            **_kwargs(conn),
            messages=investigation_messages(ctx, question, history),
            temperature=0.2,
            max_tokens=config.BYOK_MAX_TOKENS,
        )
        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
    except ByokError:
        raise
    except Exception as e:  # noqa: BLE001
        raise _normalize_error(e) from None
    _log("byok.investigate", conn, status="ok", duration_ms=round((time.time() - started) * 1000, 1))
    return {
        "answer": text,
        "model": conn.model,
        "provider": conn.provider,
        "usage": _usage_dict(usage),
    }


def _usage_dict(usage: Any) -> dict:
    if usage is None:
        return {}
    return {
        "promptTokens": getattr(usage, "prompt_tokens", None),
        "completionTokens": getattr(usage, "completion_tokens", None),
        "totalTokens": getattr(usage, "total_tokens", None),
    }


async def stream(
    conn: Connection,
    ctx: dict,
    question: str,
    history: list[dict] | None = None,
) -> AsyncIterator[dict]:
    """Yield SSE-ready events: {"type": "delta"|"done"|"error", ...}."""
    started = time.time()
    ttft_ms: float | None = None
    try:
        resp = await litellm.acompletion(
            **_kwargs(conn),
            messages=investigation_messages(ctx, question, history),
            temperature=0.2,
            max_tokens=config.BYOK_MAX_TOKENS,
            stream=True,
        )
        async for chunk in resp:
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError, KeyError):
                delta = None
            if delta:
                if ttft_ms is None:
                    ttft_ms = round((time.time() - started) * 1000, 1)
                yield {"type": "delta", "text": delta}
    except ByokError as e:
        _log("byok.stream", conn, status="error", error=e.code)
        yield {"type": "error", "code": e.code, "message": str(e)}
        return
    except Exception as e:  # noqa: BLE001
        err = _normalize_error(e)
        _log("byok.stream", conn, status="error", error=err.code)
        yield {"type": "error", "code": err.code, "message": str(err)}
        return
    _log(
        "byok.stream",
        conn,
        status="ok",
        duration_ms=round((time.time() - started) * 1000, 1),
        ttft_ms=ttft_ms,
    )
    yield {
        "type": "done",
        "provider": conn.provider,
        "model": conn.model,
        "durationMs": round((time.time() - started) * 1000, 1),
        "ttftMs": ttft_ms,
    }
