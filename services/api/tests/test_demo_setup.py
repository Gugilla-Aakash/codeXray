"""One-click demo bootstrap (POST /api/demo/setup).

Reuses the client/DB owner (test_api.py) so the whole suite shares one engine.
"""

from __future__ import annotations

from test_api import client

from app import config as app_config


def test_demo_setup_creates_seeded_project():
    r = client.post("/api/demo/setup")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"].startswith("prj_")
    assert body["environment"] == "demo"
    assert body["api_key"].startswith("cxr_") or len(body["api_key"]) > 16

    # The project must be immediately usable: graph loads with seeded nodes.
    g = client.get(f"/api/projects/{body['id']}/graph", headers={"X-API-Key": body["api_key"]})
    assert g.status_code == 200, g.text
    graph = g.json()
    assert graph["nodes"], "demo project must arrive pre-seeded"
    assert graph["summary"]["services"] >= 1

    # And it has the incident (so AI summary / replay work out of the box).
    inc = client.get(f"/api/projects/{body['id']}/incidents", headers={"X-API-Key": body["api_key"]})
    assert inc.status_code == 200
    assert inc.json(), "demo project must ship with an incident"


def test_demo_setup_disabled_by_flag(monkeypatch):
    monkeypatch.setattr(app_config, "DEMO_SETUP", False)
    assert client.post("/api/demo/setup").status_code == 404


def test_demo_setup_rate_limited():
    # Exhaust the rolling window (10/min) with cheap failures avoided by
    # simply calling until 429; happy-path cost is one seeded project each.
    saw_429 = False
    for _ in range(11):
        if client.post("/api/demo/setup").status_code == 429:
            saw_429 = True
            break
    assert saw_429, "demo setup must be rate-limited"
