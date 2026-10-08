"""Phase-2 demo controls: ⚡ inject failure, pulse events, evidence fields.

Reuses the client/DB owner (test_api.py) so the whole suite shares one engine.
"""

from __future__ import annotations

from test_api import client

from app.seed import build_demo_events, build_pulse_events


def _project(name="inject"):
    r = client.post("/api/projects", json={"name": name, "environment": "test"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["id"], body["api_key"]


def _h(key: str) -> dict:
    return {"X-API-Key": key}


def test_inject_creates_incident_with_evidence():
    pid, key = _project()
    before = client.get(f"/api/projects/{pid}/incidents", headers=_h(key)).json()

    r = client.post(f"/api/projects/{pid}/demo/inject", headers=_h(key))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] > 0

    after = client.get(f"/api/projects/{pid}/incidents", headers=_h(key)).json()
    assert len(after) == len(before) + 1

    rc = after[-1]["root_cause"]
    assert rc["service"] == "postgres"
    assert rc["confidence"] >= 50
    # Evidence for the UI + AI: blamed span and the signals that scored it.
    assert rc.get("span_id"), "root cause must carry span_id"
    assert rc.get("signals"), "root cause must carry scoring signals"
    assert "error" in rc["signals"]
    assert rc["propagation"], "propagation path must be present"

    # Injecting again creates ANOTHER incident (unique tags, no wipe).
    r2 = client.post(f"/api/projects/{pid}/demo/inject", headers=_h(key))
    assert r2.status_code == 200
    after2 = client.get(f"/api/projects/{pid}/incidents", headers=_h(key)).json()
    assert len(after2) == len(before) + 2


def test_inject_requires_api_key():
    pid, _ = _project("inject-auth")
    assert client.post(f"/api/projects/{pid}/demo/inject").status_code == 401
    assert (
        client.post(f"/api/projects/{pid}/demo/inject", headers={"X-API-Key": "bogus"}).status_code
        == 401
    )


def test_inject_rate_limited():
    pid, key = _project("inject-rl")
    codes = [
        client.post(f"/api/projects/{pid}/demo/inject", headers=_h(key)).status_code
        for _ in range(9)
    ]
    assert 429 in codes, f"expected a 429 within 9 injects, got {codes}"


def test_pulse_events_are_all_success_with_unique_spans():
    events = build_pulse_events("pt1")
    assert len(events) >= 4
    assert all(e["status"] == "success" for e in events)
    span_ids = [e["span_id"] for e in events]
    assert len(span_ids) == len(set(span_ids)), "span ids must be unique"
    # No error payloads → ingest will never open an incident from a pulse.
    assert all("error" not in e for e in events)


def test_inject_only_events_have_no_healthy_trace():
    inc = build_demo_events(tag="x", incident_only=True)
    full = build_demo_events(tag="x")
    assert len(inc) == 6
    assert len(full) == 12
    assert all((e["status"] or "").lower() == "error" or e["service"] == "auth-service"
               for e in inc)
