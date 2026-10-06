"""BYOK AI investigation — LiteLLM routing, errors, streaming, security.

Every provider call is mocked: the suite never makes a real network request.
Reuses the client/DB owner (test_api.py) so the whole suite shares one engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from types import SimpleNamespace

import litellm
import pytest
from test_api import client

from app import ai as ai_engine
from app import byok as byok_engine

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _project(name="byok"):
    r = client.post("/api/projects", json={"name": name, "environment": "test"})
    assert r.status_code == 201, r.text
    b = r.json()
    return b["id"], b["api_key"]


def _h(key: str) -> dict:
    return {"X-API-Key": key}


def _seed_incident(key: str) -> str:
    trace_id = f"byok-{time.time_ns()}"
    now = time.time()
    events = [
        {
            "trace_id": trace_id,
            "span_id": f"{trace_id}-s1",
            "service": "frontend",
            "operation": "POST /checkout",
            "timestamp": now,
            "duration_ms": 1200,
            "status": "error",
            "error": {"type": "Upstream", "message": "checkout failed"},
            "request": {"method": "POST", "path": "/checkout"},
            "response": {"status_code": 500},
            "metadata": {"password": "sekret-should-redact"},
        },
        {
            "trace_id": trace_id,
            "span_id": f"{trace_id}-s2",
            "parent_span_id": f"{trace_id}-s1",
            "service": "payments",
            "operation": "charge",
            "timestamp": now + 0.2,
            "duration_ms": 900,
            "status": "error",
            "error": {"type": "CardDeclined", "message": "card declined"},
        },
    ]
    r = client.post("/api/telemetry", json={"events": events}, headers=_h(key))
    assert r.status_code == 200, r.text
    assert r.json()["incident_ids"]
    return r.json()["incident_ids"][0]


class _Resp:
    def __init__(self, content="ok", model="mock-model"):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]
        self.model = model
        self.usage = None


def _chunk(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


def _fake_ok(calls: list | None = None, content="ok", model="mock-model"):
    async def _f(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return _Resp(content, model)

    return _f


def _fake_raise(exc: Exception):
    async def _f(**kwargs):
        raise exc

    return _f


def _conn(provider="openai", model="gpt-4o", api_key="user-key", base_url=None):
    return byok_engine.Connection(
        id="conn_test",
        project_id="prj_test",
        provider=provider,
        model=model,
        base_url=base_url,
        created_at=0.0,
        api_key=api_key,
        last_used=0.0,
    )


# --------------------------------------------------------------------------
# routing — provider selection drives the LiteLLM namespace
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "provider,model,expected_model,expected_base",
    [
        ("openai", "gpt-4o-mini", "openai/gpt-4o-mini", None),
        ("groq", "openai/gpt-oss-120b", "groq/openai/gpt-oss-120b", None),
        ("anthropic", "claude-3-5-haiku-latest", "anthropic/claude-3-5-haiku-latest", None),
        ("gemini", "gemini-2.0-flash", "gemini/gemini-2.0-flash", None),
        ("moonshot", "kimi-k2", "moonshot/kimi-k2", "https://api.moonshot.ai/v1"),
        (
            "openrouter",
            "anthropic/claude-3.5-sonnet",
            "openrouter/anthropic/claude-3.5-sonnet",
            None,
        ),
        ("custom", "my-model", "openai/my-model", "http://localhost:11434/v1"),
    ],
)
def test_provider_routing(monkeypatch, provider, model, expected_model, expected_base):
    calls: list = []
    monkeypatch.setattr(byok_engine.litellm, "acompletion", _fake_ok(calls))
    base = "http://localhost:11434/v1" if provider == "custom" else None
    res = asyncio.run(byok_engine.test_connection(provider, model, "user-key", base))
    assert res["success"] is True
    assert calls[0]["model"] == expected_model
    assert calls[0]["api_base"] == expected_base
    assert calls[0]["api_key"] == "user-key"


def test_moonshot_kimi_never_routes_to_openai():
    model_id = byok_engine.litellm_model("moonshot", "kimi-k2")
    assert model_id == "moonshot/kimi-k2"
    assert not model_id.startswith("openai/")
    _, base = byok_engine._connection_spec("moonshot", "kimi-k2", None)
    assert base == "https://api.moonshot.ai/v1"
    assert "openai.com" not in (base or "")


def test_already_namespaced_model_is_not_double_prefixed():
    assert byok_engine.litellm_model("moonshot", "moonshot/kimi-k2") == "moonshot/kimi-k2"


def test_custom_requires_base_url_and_noneditable_rejects_one():
    with pytest.raises(byok_engine.ByokError) as e1:
        byok_engine._connection_spec("custom", "m", None)
    assert e1.value.code == "invalid_config"
    with pytest.raises(byok_engine.ByokError) as e2:
        byok_engine._connection_spec("anthropic", "claude", "https://evil.example")
    assert e2.value.code == "invalid_config"


def test_unknown_provider_rejected():
    with pytest.raises(byok_engine.ByokError) as e:
        byok_engine._connection_spec("not-a-provider", "m", None)
    assert e.value.code == "invalid_config"


# --------------------------------------------------------------------------
# error normalization
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc,code,status",
    [
        (litellm.AuthenticationError("bad key", "openai", "gpt-4o"), "auth_failed", 401),
        (litellm.RateLimitError("slow down", "openai", "gpt-4o"), "rate_limited", 429),
        (litellm.NotFoundError("no such model", "openai", "gpt-4o"), "model_unavailable", 404),
        (litellm.BadRequestError("bad request", "gpt-4o", "openai"), "invalid_config", 400),
        (litellm.APIConnectionError("boom", "openai", "gpt-4o"), "network_error", 502),
        (litellm.Timeout("timed out", "gpt-4o", "openai"), "timeout", 504),
        (litellm.APIError(500, "generic", "openai", "gpt-4o"), "provider_error", 502),
    ],
)
def test_error_normalization(monkeypatch, exc, code, status):
    monkeypatch.setattr(byok_engine.litellm, "acompletion", _fake_raise(exc))
    with pytest.raises(byok_engine.ByokError) as ei:
        asyncio.run(byok_engine.test_connection("openai", "gpt-4o", "k", None))
    assert ei.value.code == code
    assert ei.value.status == status


def test_timeout_is_not_misclassified_as_network_error(monkeypatch):
    # litellm.Timeout subclasses APIConnectionError; the more specific wins.
    monkeypatch.setattr(
        byok_engine.litellm, "acompletion", _fake_raise(litellm.Timeout("t", "m", "openai"))
    )
    with pytest.raises(byok_engine.ByokError) as ei:
        asyncio.run(byok_engine.test_connection("openai", "gpt-4o", "k", None))
    assert ei.value.code == "timeout"


def test_insufficient_credits_message(monkeypatch):
    exc = litellm.BadRequestError("You have insufficient credits", "m", "openai")
    monkeypatch.setattr(byok_engine.litellm, "acompletion", _fake_raise(exc))
    with pytest.raises(byok_engine.ByokError) as ei:
        asyncio.run(byok_engine.test_connection("openai", "gpt-4o", "k", None))
    assert ei.value.code == "insufficient_credits"
    assert ei.value.status == 402


# --------------------------------------------------------------------------
# security — keys never logged, never returned, never persisted
# --------------------------------------------------------------------------

def test_api_key_never_appears_in_logs_or_repr(monkeypatch, caplog):
    sentinel = "sk-supersecret-DO-NOT-LOG"
    monkeypatch.setattr(byok_engine.litellm, "acompletion", _fake_ok())
    with caplog.at_level(logging.INFO, logger="codexray.byok"):
        asyncio.run(byok_engine.test_connection("openai", "gpt-4o", sentinel, None))
        conn = _conn(api_key=sentinel)
        asyncio.run(byok_engine.complete(conn, {"incidentId": "INC-1"}, "why?", []))
    assert sentinel not in caplog.text
    assert sentinel not in repr(conn)
    assert sentinel not in json.dumps({"conn": conn.public()})


def test_connection_endpoint_never_returns_key(monkeypatch):
    pid, key = _project("byok-secret")
    monkeypatch.setattr(byok_engine.litellm, "acompletion", _fake_ok())
    r = client.post(
        f"/api/projects/{pid}/ai/connections",
        headers=_h(key),
        json={
            "provider": "moonshot",
            "apiKey": "kimi-secret-key-xyz",
            "model": "kimi-k2",
            "baseUrl": "http://localhost:11434/v1",
        },
    )
    assert r.status_code == 200, r.text
    assert "kimi-secret-key-xyz" not in r.text
    assert "kimi-secret-key-xyz" not in json.dumps(r.json())


def test_missing_api_key_is_422():
    pid, key = _project("byok-nokey")
    r = client.post(
        f"/api/projects/{pid}/ai/providers/test",
        headers=_h(key),
        json={"provider": "openai", "model": "gpt-4o", "apiKey": ""},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# context construction
# --------------------------------------------------------------------------

def test_investigation_context_is_structured_and_redacted():
    spans = [
        {
            "span_id": "s1",
            "parent_span_id": None,
            "service": "frontend",
            "operation": "POST /checkout",
            "timestamp": 100.0,
            "duration_ms": 1200,
            "status": "error",
            "error": {"type": "Upstream", "message": "checkout failed"},
            "request": {"method": "POST", "path": "/checkout"},
            "response": {"status_code": 500},
            "metadata": {"password": "sekret-should-redact"},
        },
        {
            "span_id": "s2",
            "parent_span_id": "s1",
            "service": "payments",
            "operation": "charge",
            "timestamp": 100.2,
            "duration_ms": 900,
            "status": "error",
            "error": {"type": "CardDeclined", "message": "card declined"},
            "request": {},
            "response": {},
            "metadata": {},
        },
    ]
    incident = {
        "incident_id": "INC-1001",
        "title": "checkout failed",
        "severity": "high",
        "status": "open",
        "root_cause": {"service": "payments", "reason": "card declined"},
        "affected_services": ["frontend", "payments"],
    }
    trace = {"trace_id": "t1", "root_service": "frontend", "status": "error", "duration_ms": 1200}
    ctx = byok_engine.build_investigation_context(incident, trace, spans, "cached summary")

    assert ctx["incidentId"] == "INC-1001"
    assert ctx["severity"] == "high"
    assert ctx["summary"] == "cached summary"
    assert ctx["request"]["method"] == "POST"
    assert ctx["stackTrace"] == "card declined"
    assert ctx["services"] == ["frontend", "payments"]
    assert "frontend -> payments" in ctx["dependencies"]
    assert len(ctx["timeline"]) == 2
    assert "sekret-should-redact" not in json.dumps(ctx)


def test_investigation_context_caps_spans():
    spans = [
        {
            "span_id": f"s{i}",
            "parent_span_id": None,
            "service": f"svc-{i}",
            "operation": "op",
            "timestamp": float(i),
            "duration_ms": i,
            "status": "success",
            "error": None,
        }
        for i in range(60)
    ]
    ctx = byok_engine.build_investigation_context(
        {"incident_id": "INC-1"}, {"trace_id": "t"}, spans, None
    )
    assert ctx["spanCount"] == 60
    assert ctx["spansShown"] <= 30


# --------------------------------------------------------------------------
# conversation history
# --------------------------------------------------------------------------

def test_history_is_capped_and_question_is_last():
    hist = [{"role": "user", "content": f"q{i}"} for i in range(50)]
    msgs = byok_engine.investigation_messages({"incidentId": "INC-1"}, "final question", hist)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user" and "InvestigationContext" in msgs[1]["content"]
    assert msgs[-1] == {"role": "user", "content": "final question"}
    history_turns = [m for m in msgs[2:-1] if m["content"].startswith("q")]
    assert len(history_turns) <= byok_engine.config.BYOK_MAX_HISTORY


def test_history_rejects_unknown_roles():
    msgs = byok_engine.investigation_messages(
        {"incidentId": "INC-1"}, "q", [{"role": "system", "content": "malicious"}]
    )
    # Unknown roles are coerced to user; system prompts cannot be injected.
    assert all(m["role"] != "system" for m in msgs[2:])


# --------------------------------------------------------------------------
# streaming
# --------------------------------------------------------------------------

def test_stream_collects_deltas_then_done(monkeypatch):
    async def fake_stream(**kwargs):
        async def gen():
            for t in ["Hel", "lo", "!"]:
                yield _chunk(t)

        return gen()

    monkeypatch.setattr(byok_engine.litellm, "acompletion", fake_stream)

    async def collect():
        return [ev async for ev in byok_engine.stream(_conn(), {"incidentId": "INC-1"}, "hi", [])]

    events = asyncio.run(collect())
    assert "".join(e.get("text", "") for e in events if e["type"] == "delta") == "Hello!"
    assert events[-1]["type"] == "done"
    assert events[-1]["provider"] == "openai"


def test_stream_normalizes_midstream_error(monkeypatch):
    async def fake_stream(**kwargs):
        async def gen():
            yield _chunk("par")
            raise litellm.RateLimitError("slow", "openai", "gpt-4o")

        return gen()

    monkeypatch.setattr(byok_engine.litellm, "acompletion", fake_stream)

    async def collect():
        return [ev async for ev in byok_engine.stream(_conn(), {"incidentId": "INC-1"}, "hi", [])]

    events = asyncio.run(collect())
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "rate_limited"
    # Provider-neutral message; the raw provider payload is not echoed.
    assert events[-1]["message"] == "Provider rate limit — try again shortly."


def test_stream_endpoint_emits_sse(monkeypatch):
    pid, key = _project("byok-sse")
    incident = _seed_incident(key)

    async def fake_stream(**kwargs):
        async def gen():
            for t in ["The ", "payments ", "service failed."]:
                yield _chunk(t)

        return gen()

    monkeypatch.setattr(byok_engine.litellm, "acompletion", fake_stream)

    c = client.post(
        f"/api/projects/{pid}/ai/connections",
        headers=_h(key),
        json={"provider": "openai", "apiKey": "k", "model": "gpt-4o"},
    )
    assert c.status_code == 200, c.text
    cid = c.json()["connectionId"]

    r = client.post(
        f"/api/projects/{pid}/ai/investigate/stream",
        headers=_h(key),
        json={"connectionId": cid, "incidentId": incident, "message": "why?", "history": []},
    )
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers["content-type"]
    assert '"type": "delta"' in r.text
    assert '"type": "done"' in r.text
    assert "payments" in r.text


# --------------------------------------------------------------------------
# endpoints / connection lifecycle
# --------------------------------------------------------------------------

def test_providers_endpoint_lists_registry():
    pid, key = _project("byok-providers")
    r = client.get(f"/api/projects/{pid}/ai/providers", headers=_h(key))
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()["providers"]}
    assert {"openai", "groq", "anthropic", "gemini", "moonshot", "openrouter", "custom"} <= ids
    assert "apiKey" not in r.text


def test_investigate_end_to_end(monkeypatch):
    pid, key = _project("byok-e2e")
    incident = _seed_incident(key)
    monkeypatch.setattr(
        byok_engine.litellm,
        "acompletion",
        _fake_ok(content="The payments service declined the card.", model="mock-model"),
    )
    c = client.post(
        f"/api/projects/{pid}/ai/connections",
        headers=_h(key),
        json={
            "provider": "moonshot",
            "apiKey": "kimi-key",
            "model": "kimi-k2",
            "baseUrl": "http://localhost:11434/v1",
        },
    )
    assert c.status_code == 200, c.text
    assert c.json()["provider"] == "moonshot"
    cid = c.json()["connectionId"]

    r = client.post(
        f"/api/projects/{pid}/ai/investigate",
        headers=_h(key),
        json={"connectionId": cid, "incidentId": incident, "message": "why?", "history": []},
    )
    assert r.status_code == 200, r.text
    assert "payments" in r.json()["answer"]
    assert r.json()["provider"] == "moonshot"

    # Disconnect drops the key from memory; further use is a clean 404.
    d = client.delete(f"/api/projects/{pid}/ai/connections/{cid}", headers=_h(key))
    assert d.status_code == 204
    r2 = client.post(
        f"/api/projects/{pid}/ai/investigate",
        headers=_h(key),
        json={"connectionId": cid, "incidentId": incident, "message": "why?", "history": []},
    )
    assert r2.status_code == 404


def test_connection_is_scoped_to_project(monkeypatch):
    pid_a, key_a = _project("byok-scope-a")
    pid_b, key_b = _project("byok-scope-b")
    incident_b = _seed_incident(key_b)
    monkeypatch.setattr(byok_engine.litellm, "acompletion", _fake_ok())
    c = client.post(
        f"/api/projects/{pid_a}/ai/connections",
        headers=_h(key_a),
        json={"provider": "openai", "apiKey": "k", "model": "gpt-4o"},
    )
    assert c.status_code == 200, c.text
    cid = c.json()["connectionId"]

    r = client.post(
        f"/api/projects/{pid_b}/ai/investigate",
        headers=_h(key_b),
        json={"connectionId": cid, "incidentId": incident_b, "message": "why?", "history": []},
    )
    assert r.status_code == 404


def test_connect_rejects_invalid_key(monkeypatch):
    pid, key = _project("byok-badkey")
    monkeypatch.setattr(
        byok_engine.litellm,
        "acompletion",
        _fake_raise(litellm.AuthenticationError("bad", "openai", "gpt-4o")),
    )
    r = client.post(
        f"/api/projects/{pid}/ai/connections",
        headers=_h(key),
        json={"provider": "openai", "apiKey": "wrong-key", "model": "gpt-4o"},
    )
    assert r.status_code == 401
    assert "wrong-key" not in r.text
    assert r.json()["detail"]["code"] == "auth_failed"


def test_connection_store_ttl_expiry(monkeypatch):
    store = byok_engine.ConnectionStore(ttl_s=0.5)
    conn = store.create("prj", "openai", "gpt-4o", "k", None)
    assert store.get("prj", conn.id).id == conn.id
    conn.last_used = time.time() - 10
    with pytest.raises(byok_engine.ByokError) as ei:
        store.get("prj", conn.id)
    assert ei.value.code == "connection_not_found"


# --------------------------------------------------------------------------
# the automatic summary is untouched and still on CodeXRay's own key
# --------------------------------------------------------------------------

def test_automatic_summary_still_uses_codexray_groq(monkeypatch):
    called: list = []

    async def fake_call(messages):
        called.append(messages)
        return "CodeXRay summary text.", "codexray-groq-model"

    monkeypatch.setattr(ai_engine, "is_enabled", lambda: True)
    monkeypatch.setattr(ai_engine, "call_groq", fake_call)

    pid, key = _project("byok-summary")
    incident = _seed_incident(key)
    r = client.post(f"/api/incidents/{incident}/ai-summary", headers=_h(key))
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == "CodeXRay summary text."
    assert r.json()["model"] == "codexray-groq-model"
    assert len(called) == 1


# --------------------------------------------------------------------------
# SSRF guard — user-supplied base URLs never reach a private socket
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata service
        "https://10.0.0.5/internal",                  # RFC1918
        "https://192.168.1.1:8443/",
        "https://172.31.255.254/",
        "https://[fd00::1]/",                         # IPv6 unique-local
        "https://[fe80::1]/",                         # IPv6 link-local
        "http://8.8.8.8/v1",                          # http to a public IP
        "ftp://api.openai.com/v1",                    # non-http scheme
        "file:///etc/passwd",
        "https://user:pass@api.openai.com/v1",        # embedded credentials
        "https://@api.openai.com/v1",                 # empty userinfo
        "not-a-url",
        "",
    ],
)
def test_ssrf_guard_rejects_dangerous_base_urls(url):
    from app.security import BaseUrlError, validate_base_url

    with pytest.raises(BaseUrlError):
        validate_base_url(url)


def test_ssrf_guard_allows_loopback_without_dns():
    from app.security import validate_base_url

    for url in ("http://localhost:11434/v1", "http://127.0.0.1:8000/v1", "https://[::1]/v1"):
        assert validate_base_url(url) == url


def test_ssrf_guard_checks_dns_resolved_ips(monkeypatch):
    import ipaddress

    from app import security
    from app.security import BaseUrlError, validate_base_url

    def _dns(ips):
        return lambda host: [ipaddress.ip_address(i) for i in ips]

    # Public resolution -> allowed.
    monkeypatch.setattr(security, "_resolve_host_ips", _dns(["104.18.7.192"]))
    assert validate_base_url("https://api.openai.com/v1") == "https://api.openai.com/v1"

    # Hostname resolving into the private range -> rejected.
    monkeypatch.setattr(security, "_resolve_host_ips", _dns(["10.1.2.3"]))
    with pytest.raises(BaseUrlError):
        validate_base_url("https://llm.corp.internal/v1")

    # Mixed public + private (rebinding bait) -> rejected (fail closed).
    monkeypatch.setattr(security, "_resolve_host_ips", _dns(["104.18.7.192", "192.168.0.10"]))
    with pytest.raises(BaseUrlError):
        validate_base_url("https://innocent.example/v1")

    # Unresolvable host -> rejected (fail closed).
    def _boom(host):
        raise OSError("no dns")

    monkeypatch.setattr(security, "_resolve_host_ips", _boom)
    with pytest.raises(BaseUrlError):
        validate_base_url("https://nope.invalid/v1")


def test_ssrf_guard_blocks_byok_before_any_provider_call(monkeypatch):
    # Domain layer: _connection_spec raises a user-safe ByokError (400)
    # before LiteLLM is ever invoked.
    with pytest.raises(byok_engine.ByokError) as e1:
        byok_engine._connection_spec("custom", "m", "http://169.254.169.254/")
    assert e1.value.code == "invalid_base_url"
    assert e1.value.status == 400

    calls: list = []
    monkeypatch.setattr(byok_engine.litellm, "acompletion", _fake_ok(calls))
    assert calls == []  # nothing called the provider yet

    # Edge layer: the schema validator turns it into a 422 before any handler.
    pid, key = _project("byok-ssrf")
    r = client.post(
        f"/api/projects/{pid}/ai/providers/test",
        headers=_h(key),
        json={
            "provider": "custom",
            "model": "m",
            "apiKey": "k",
            "baseUrl": "http://169.254.169.254/latest/meta-data/",
        },
    )
    assert r.status_code == 422
    assert "Base URL must use" in r.text  # safe policy message, not a stack trace
    assert "Traceback" not in r.text
    assert calls == []  # provider client still untouched
