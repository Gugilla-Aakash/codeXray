"""CodeXRay API — /api/logs tests (auth, tolerance, redaction, filters)."""

from __future__ import annotations

import os
import time

DB_PATH = "/tmp/opencode/codexray-test-logs.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["GROQ_API_KEY"] = ""
os.environ["DEMO_PULSE"] = "0"
os.environ["DEMO_SETUP"] = "1"

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

init_db()
client = TestClient(app)


def _project() -> tuple[str, str]:
    r = client.post("/api/projects", json={"name": "logs", "environment": "test"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["id"], body["api_key"]


def _h(key: str) -> dict:
    return {"X-API-Key": key}


def test_logs_require_auth():
    pid, key = _project()
    assert client.post("/api/logs", json={"lines": []}).status_code == 401
    assert (
        client.post("/api/logs", json={"lines": []}, headers=_h("bogus")).status_code
        == 401
    )
    other, _ = _project()
    assert (
        client.get(f"/api/projects/{other}/logs", headers=_h(key)).status_code == 403
    )


def test_logs_accept_batch_and_serve_newest_first():
    pid, key = _project()
    now = time.time()
    lines = [
        {"level": "info", "message": "boot", "ts": now - 2, "service": "api"},
        {"level": "error", "message": "boom", "ts": now - 1, "service": "api"},
        {"level": "warn", "message": "slow", "ts": now, "service": "worker"},
    ]
    r = client.post("/api/logs", json={"lines": lines}, headers=_h(key))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 3

    got = client.get(f"/api/projects/{pid}/logs", headers=_h(key)).json()
    assert len(got) == 3
    assert got[0]["message"] == "slow", "newest first"
    assert got[0]["level"] == "warn"
    assert got[-1]["message"] == "boot"

    only_err = client.get(
        f"/api/projects/{pid}/logs?level=error", headers=_h(key)
    ).json()
    assert [x["message"] for x in only_err] == ["boom"]


def test_logs_tolerant_and_redacted():
    pid, key = _project()
    r = client.post(
        "/api/logs",
        json={"lines": [{"message": "ok line"}, {"message": ""}]},
        headers=_h(key),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 1
    assert len(body["rejected"]) == 1

    r2 = client.post(
        "/api/logs",
        json={
            "lines": [
                {"message": "login failed password=hunter2 api_key=sk-abc123 user=bob"}
            ]
        },
        headers=_h(key),
    )
    assert r2.status_code == 200
    got = client.get(f"/api/projects/{pid}/logs", headers=_h(key)).json()
    msg = next(x["message"] for x in got if "login failed" in x["message"])
    assert "hunter2" not in msg
    assert "sk-abc123" not in msg
    assert "[REDACTED]" in msg
    assert "user=bob" in msg


def test_logs_level_sniff_from_message():
    pid, key = _project()
    r = client.post(
        "/api/logs",
        json={"lines": [{"level": "info", "message": "ERROR: disk full"}]},
        headers=_h(key),
    )
    assert r.status_code == 200
    got = client.get(f"/api/projects/{pid}/logs", headers=_h(key)).json()
    assert got[0]["level"] == "error"


def test_logs_websocket_broadcast():
    from fastapi.testclient import TestClient as TC

    pid, key = _project()
    ws_client = TC(app)
    http = TC(app)
    with ws_client.websocket_connect(
        f"/api/projects/{pid}/stream", subprotocols=["codexray.v1", key]
    ) as ws:
        assert ws.receive_json()["type"] == "connected"
        r = http.post(
            "/api/logs",
            json={"lines": [{"level": "error", "message": "ws log line"}]},
            headers=_h(key),
        )
        assert r.status_code == 200
        msg = ws.receive_json()
        assert msg["type"] == "log"
        assert msg["message"] == "ws log line"
        assert msg["level"] == "error"
