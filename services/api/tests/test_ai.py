"""CodeXRay AI — incident summary tests (generic, any project).

Reuses the client/DB owner (test_api.py) so the full suite shares ONE engine
and ONE unlink at import — no SQLite inode race, no readonly-DB flakes.
"""

from __future__ import annotations

import time

from test_api import client

from app import ai as ai_engine


def _project(name="shop"):
    r = client.post("/api/projects", json={"name": name, "environment": "test"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["id"], body["api_key"]


def _h(key: str) -> dict:
    return {"X-API-Key": key}


def _seed_error_trace(key: str, trace_id: str = "ai-t1"):
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
            "metadata": {"password": "should-never-leave-server"},
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
    assert r.json()["incident_ids"], "error trace must raise an incident"
    return r.json()["incident_ids"][0]


def test_ai_disabled_returns_503(monkeypatch):
    _, key = _project("ai-off")
    iid = _seed_error_trace(key, trace_id=f"off-{time.time_ns()}")
    monkeypatch.setattr(ai_engine, "is_enabled", lambda: False)
    r = client.post(f"/api/incidents/{iid}/ai-summary", headers=_h(key))
    assert r.status_code == 503
    assert "GROQ" in r.json()["detail"]


def test_ai_summary_caches_and_scopes(monkeypatch):
    pid, key = _project("ai-cache")
    _, other_key = _project("ai-other")
    iid = _seed_error_trace(key, trace_id=f"cache-{time.time_ns()}")
    calls: list = []

    async def fake_call(messages):
        calls.append(messages)
        return "Probable root cause: payments card declined.", "mock-model"

    monkeypatch.setattr(ai_engine, "is_enabled", lambda: True)
    monkeypatch.setattr(ai_engine, "call_groq", fake_call)

    r = client.post(f"/api/incidents/{iid}/ai-summary", headers=_h(key))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False
    assert "payments" in body["summary"]
    assert len(calls) == 1
    # Groq must never see the raw secret even though ingest stored it redacted.
    assert "should-never-leave-server" not in str(calls[0])

    r2 = client.post(f"/api/incidents/{iid}/ai-summary", headers=_h(key))
    assert r2.json()["cached"] is True
    assert len(calls) == 1, "second call must serve DB cache"

    # Cross-project access to the same incident id must 404, never leak.
    r3 = client.post(f"/api/incidents/{iid}/ai-summary", headers=_h(other_key))
    assert r3.status_code == 404


def test_build_context_is_redacted_and_capped():
    spans = [
        {
            "span_id": f"s{i}",
            "parent_span_id": None,
            "service": f"svc-{i}",
            "operation": "op",
            "timestamp": 1000 + i,
            "duration_ms": i,
            "status": "success",
            "error": None,
        }
        for i in range(60)
    ]
    ctx = ai_engine.build_incident_context(
        {"trace_id": "t", "root_service": "svc-0", "status": "success", "duration_ms": 5},
        spans,
        None,
        None,
    )
    assert ctx["span_count"] == 60
    assert ctx["spans_shown"] <= 30
