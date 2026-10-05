"""CodeXRay API — end-to-end tests (PRD §36 acceptance criteria)."""

from __future__ import annotations

import os
import time

import pytest

DB_PATH = "/tmp/opencode/codexray-test.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

# Hermetic: a developer's services/api/.env must not change test outcomes.
# load_dotenv() does not override existing vars, so blanking these first keeps
# the suite on the "unconfigured" defaults (open licensing, AI disabled).
os.environ["GROQ_API_KEY"] = ""
os.environ["CODEXRAY_LICENSE_KEY"] = ""
# Pulse loop would race the assertions with background writes; keep it off
# in tests (the loop itself is exercised via build_pulse_events unit tests).
os.environ["DEMO_PULSE"] = "0"
os.environ["DEMO_SETUP"] = "1"

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

init_db()
client = TestClient(app)


def _project() -> tuple[str, str]:
    r = client.post("/api/projects", json={"name": "checkout", "environment": "test"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["id"], body["api_key"]


def _h(key: str) -> dict:
    return {"X-API-Key": key}


def test_full_flow_project_telemetry_graph_trace():
    pid, key = _project()
    event = {
        "trace_id": "trace-123",
        "span_id": "span-456",
        "parent_span_id": "span-111",
        "service": "order-service",
        "operation": "POST /orders",
        "timestamp": 1768724301,
        "duration_ms": 248,
        "status": "success",
        "request": {"method": "POST", "path": "/orders"},
        "response": {"status_code": 200},
        "metadata": {"region": "ap-south-1"},
    }
    r = client.post("/api/telemetry", json=event, headers=_h(key))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1

    g = client.get(f"/api/projects/{pid}/graph", headers=_h(key)).json()
    assert any(n["id"] == "order-service" for n in g["nodes"])
    assert g["summary"]["services"] >= 1

    traces = client.get(f"/api/projects/{pid}/traces", headers=_h(key)).json()
    assert any(t["trace_id"] == "trace-123" for t in traces)

    detail = client.get("/api/traces/trace-123", headers=_h(key)).json()
    assert detail["root_service"] == "order-service"
    assert detail["spans"][0]["service"] == "order-service"


def test_tolerant_ingestion_never_crashes_batch():
    pid, key = _project()
    batch = [
        {"trace_id": "t1", "span_id": "s1", "service": "api", "timestamp": time.time()},
        {"trace_id": "t1", "service": "api", "timestamp": time.time()},  # missing span_id
        "not-a-dict",
        {"trace_id": "t1", "span_id": "s1", "service": "api", "timestamp": time.time()},  # duplicate
        {"trace_id": "t2", "span_id": "s9", "parent_span_id": "ghost", "service": "db",
         "timestamp": time.time()},  # missing parent tolerated
    ]
    r = client.post("/api/telemetry", json={"events": batch}, headers=_h(key))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 3
    assert len(body["rejected"]) == 2


def test_incident_root_cause_and_replay():
    pid, key = _project()
    r = client.post(f"/api/projects/{pid}/demo/seed?tag=t0", headers=_h(key))
    assert r.status_code == 200, r.text
    assert r.json()["incident_ids"], "seed must produce an incident"

    incidents = client.get(f"/api/projects/{pid}/incidents", headers=_h(key)).json()
    assert len(incidents) >= 1
    inc = incidents[0]
    assert inc["trace_id"] == "t0-a92fd1"
    assert inc["root_cause"]["service"] == "postgres"
    assert "postgres" in inc["affected_services"]
    assert inc["root_cause"]["confidence"] >= 50

    replay = client.get(
        f"/api/incidents/{inc['incident_id']}/replay", headers=_h(key)
    ).json()
    actions = replay["actions"]
    assert actions[0]["action"] == "START_REQUEST"
    assert actions[-1]["action"] == "END_REQUEST"
    times = [a["time"] for a in actions]
    assert times == sorted(times), "replay must be chronological"
    kinds = {a["action"] for a in actions}
    assert {"ENTER_SERVICE", "CALL_DEPENDENCY", "ERROR"} <= kinds
    err = next(a for a in actions if a["action"] == "ERROR" and a["service"] == "postgres")
    assert "2000ms" in (err["message"] or "")


def test_security_isolation_and_redaction():
    pid, key = _project()
    assert client.get(f"/api/projects/{pid}/graph").status_code == 401
    assert client.get(f"/api/projects/{pid}/graph", headers=_h("bogus")).status_code == 401
    other, _ = _project()
    r = client.get(f"/api/projects/{other}/graph", headers=_h(key))
    assert r.status_code == 403

    evil = {
        "trace_id": "sec-1",
        "span_id": "sec-s1",
        "service": "auth-service",
        "timestamp": time.time(),
        "request": {"Authorization": "Bearer hunter2", "user": "aakash"},
        "metadata": {"password": "s3cret", "region": "ap-south-1"},
    }
    assert client.post("/api/telemetry", json=evil, headers=_h(key)).status_code == 200
    detail = client.get("/api/traces/sec-1", headers=_h(key)).json()
    span = detail["spans"][0]
    assert span["request"]["Authorization"] == "[REDACTED]"
    assert span["request"]["user"] == "aakash"
    assert span["metadata"]["password"] == "[REDACTED]"
    assert span["metadata"]["region"] == "ap-south-1"


def test_cross_project_trace_ids_are_rejected():
    import time as _t

    pid_a, key_a = _project()
    pid_b, key_b = _project()
    ev = {
        "trace_id": "shared-1",
        "span_id": "shared-s1",
        "service": "api",
        "timestamp": _t.time(),
    }
    assert client.post("/api/telemetry", json=ev, headers=_h(key_a)).json()["accepted"] == 1
    # Same IDs under another project must not merge — rejected, no leak.
    r = client.post("/api/telemetry", json=ev, headers=_h(key_b)).json()
    assert r["accepted"] == 0
    assert "another project" in r["rejected"][0]["reason"]
    assert client.get(f"/api/projects/{pid_b}/traces", headers=_h(key_b)).json() == []


def test_seed_is_repeatable():
    pid, key = _project()
    first = client.post(f"/api/projects/{pid}/demo/seed?tag=r1", headers=_h(key)).json()
    second = client.post(f"/api/projects/{pid}/demo/seed?tag=r1", headers=_h(key)).json()
    assert first["incident_ids"] and second["incident_ids"]
    incidents = client.get(f"/api/projects/{pid}/incidents", headers=_h(key)).json()
    assert len(incidents) == 1
    assert incidents[0]["root_cause"]["service"] == "postgres"


def test_websocket_streams_live_events():
    from fastapi.testclient import TestClient as TC

    pid, key = _project()
    # NOTE: separate clients for WS vs HTTP — one TestClient cannot issue
    # HTTP while it holds a WebSocket open on the same portal.
    ws_client = TC(app)
    http = TC(app)
    with ws_client.websocket_connect(
        f"/api/projects/{pid}/stream", subprotocols=["codexray.v1", key]
    ) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "connected"
        ev = {
            "trace_id": "ws-1",
            "span_id": "ws-s1",
            "service": "payment-service",
            "operation": "charge",
            "timestamp": time.time(),
            "status": "error",
            "error": {"type": "CardDeclined", "message": "declined"},
        }
        r = http.post("/api/telemetry", json=ev, headers=_h(key))
        assert r.status_code == 200
        kinds = set()
        # This error event fans out to exactly 3 messages: error,
        # service_status (healthy -> error), and incident.
        for _ in range(3):
            kinds.add(ws.receive_json()["type"])
        assert kinds == {"error", "service_status", "incident"}


def test_project_list_is_tenant_scoped():
    """GET /api/projects returns ONLY the caller's project — never the fleet."""
    pid_a, key_a = _project()
    pid_b, _key_b = _project()

    r = client.get("/api/projects", headers=_h(key_a))
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert ids == [pid_a], f"key A must see exactly its own project, got {ids}"
    assert pid_b not in ids

    assert client.get("/api/projects").status_code == 401


def test_websocket_rejects_missing_or_wrong_credentials():
    """Stream auth rides Sec-WebSocket-Protocol — no/wrong key => denied 4401."""
    from fastapi.testclient import TestClient as TC
    from starlette.websockets import WebSocketDisconnect

    pid, key = _project()
    ws_client = TC(app)

    # No credentials at all (the legacy ?token= no longer exists).
    with (
        pytest.raises(WebSocketDisconnect) as e1,
        ws_client.websocket_connect(f"/api/projects/{pid}/stream?token={key}"),
    ):
        pass
    assert e1.value.code == 4401

    # Wrong key offered as a subprotocol.
    with pytest.raises(WebSocketDisconnect) as e2, ws_client.websocket_connect(
        f"/api/projects/{pid}/stream", subprotocols=["codexray.v1", "cxr_wrong_key"]
    ):
        pass
    assert e2.value.code == 4401

    # Subprotocol offered but missing the fixed token — still denied.
    with pytest.raises(WebSocketDisconnect) as e3, ws_client.websocket_connect(
        f"/api/projects/{pid}/stream", subprotocols=[key]
    ):
        pass
    assert e3.value.code == 4401


def test_supabase_health_does_not_leak_exception_details(monkeypatch):
    """Health failures return a generic stub; exception text stays in logs."""
    from app import supabase_client

    def _boom():
        raise RuntimeError(
            "password=hunter2 connect failed to postgres://user@10.0.0.5:5432/db"
        )

    monkeypatch.setattr(supabase_client, "get_supabase", _boom)
    r = client.get("/api/supabase/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "unavailable"
    for secret in ("hunter2", "10.0.0.5", "postgres://", "Traceback"):
        assert secret not in r.text
