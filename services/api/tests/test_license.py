"""SaaS license gate: CODEXRAY_LICENSE_KEY in .env gates project creation.

Empty/unset => open mode (open-source default). Set => POST /api/projects and
POST /api/demo/setup require a matching X-License-Key header.
"""

from __future__ import annotations

import pytest
from test_api import client

from app import config as app_config
from app.main import license_fail_limiter


@pytest.fixture(autouse=True)
def _fresh_license_fail_budget():
    """The failure limiter is process-global; start every test with a clean slate."""
    license_fail_limiter._hits.clear()
    yield
    license_fail_limiter._hits.clear()


def test_projects_open_without_license():
    r = client.post("/api/projects", json={"name": "open-project"})
    assert r.status_code == 201, r.text
    assert r.json()["api_key"].startswith("cxr_")


def test_projects_ignore_license_header_if_sent():
    r = client.post(
        "/api/projects",
        json={"name": "legacy-header"},
        headers={"X-License-Key": "ignored"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["api_key"].startswith("cxr_")


def test_license_status_open_mode():
    r = client.get("/api/license")
    assert r.status_code == 200
    assert r.json() == {"required": False}


def test_license_required_missing_header(monkeypatch):
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    r = client.post("/api/projects", json={"name": "no-key"})
    assert r.status_code == 401, r.text
    assert "license" in r.json()["detail"]


def test_license_required_wrong_key(monkeypatch):
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    r = client.post(
        "/api/projects",
        json={"name": "wrong-key"},
        headers={"X-License-Key": "cxrl_nope"},
    )
    assert r.status_code == 401, r.text
    assert "license" in r.json()["detail"]


def test_license_correct_key_creates_project(monkeypatch):
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    r = client.post(
        "/api/projects",
        json={"name": "licensed"},
        headers={"X-License-Key": "cxrl_valid"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["api_key"].startswith("cxr_")


def test_license_any_of_multiple_keys(monkeypatch):
    monkeypatch.setattr(
        app_config, "LICENSE_KEYS", frozenset({"cxrl_one", "cxrl_two"})
    )
    for key in ("cxrl_one", "cxrl_two"):
        r = client.post(
            "/api/projects",
            json={"name": f"multi-{key}"},
            headers={"X-License-Key": key},
        )
        assert r.status_code == 201, r.text


def test_license_status_required_mode(monkeypatch):
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    r = client.get("/api/license")
    assert r.status_code == 200
    assert r.json() == {"required": True}


def test_demo_setup_gated_without_license(monkeypatch):
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    r = client.post("/api/demo/setup")
    assert r.status_code == 401, r.text


def test_demo_setup_gated_with_wrong_license(monkeypatch):
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    r = client.post("/api/demo/setup", headers={"X-License-Key": "nope"})
    assert r.status_code == 401, r.text


def test_demo_setup_opens_with_license(monkeypatch):
    from app.main import demo_setup_limiter

    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    # Earlier tests in the suite exhaust the 10/min window; clear it so the
    # license assertion isn't shadowed by an unrelated 429.
    demo_setup_limiter._hits.clear()
    r = client.post("/api/demo/setup", headers={"X-License-Key": "cxrl_valid"})
    assert r.status_code == 201, r.text
    assert r.json()["environment"] == "demo"


def test_licensed_creation_still_yields_working_project(monkeypatch):
    """A project created under a license behaves like any other project."""
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    r = client.post(
        "/api/projects",
        json={"name": "post-license"},
        headers={"X-License-Key": "cxrl_valid"},
    )
    assert r.status_code == 201, r.text
    pid, key = r.json()["id"], r.json()["api_key"]
    g = client.get(f"/api/projects/{pid}/graph", headers={"X-API-Key": key})
    assert g.status_code == 200, g.text


def test_other_endpoints_not_gated(monkeypatch):
    """License gates creation only — health and existing-key routes stay open."""
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    assert client.get("/health").status_code == 200
    r = client.post(
        "/api/telemetry",
        json={"trace_id": "t1", "span_id": "s1", "service": "svc", "timestamp": 1.0},
        headers={"X-API-Key": "cxr_bogus"},
    )
    assert r.status_code == 401  # API-key auth, not license auth


def test_license_brute_force_is_rate_limited(monkeypatch):
    """Failed attempts burn a per-IP budget: 5x401, then 429. A valid key
    still works — the budget only counts wrong guesses."""
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))

    for i in range(5):
        r = client.post(
            "/api/projects",
            json={"name": f"brute-{i}"},
            headers={"X-License-Key": "cxrl_wrong"},
        )
        assert r.status_code == 401, r.text

    r = client.post(
        "/api/projects",
        json={"name": "brute-overflow"},
        headers={"X-License-Key": "cxrl_wrong"},
    )
    assert r.status_code == 429
    assert "Too many license attempts" in r.json()["detail"]

    # Budget tracks failures only — the legitimate key passes the limiter.
    r = client.post(
        "/api/projects",
        json={"name": "legit-after-429"},
        headers={"X-License-Key": "cxrl_valid"},
    )
    assert r.status_code == 201, r.text


def test_license_success_does_not_consume_budget(monkeypatch):
    monkeypatch.setattr(app_config, "LICENSE_KEYS", frozenset({"cxrl_valid"}))
    for i in range(8):
        r = client.post(
            "/api/projects",
            json={"name": f"ok-{i}"},
            headers={"X-License-Key": "cxrl_valid"},
        )
        assert r.status_code == 201, r.text
