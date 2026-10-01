"""CLI license gate for `codexray init` — flag/env/box resolution, header
sends, the invalid-key exit path, CODEXRAY_API defaults, and the open-server
skip (GET /api/license). Stdlib only (no API needed)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest
from codexray import cli


class _Handler(BaseHTTPRequestHandler):
    """Canned API responder: GET /api/license + POST /api/projects.

    Records the last POST headers so tests can assert on X-License-Key.
    """

    status = 201
    license_required = True  # serve GET /api/license with this value
    license_endpoint = True  # False → 501, simulating a pre-gate server
    last_headers: ClassVar[dict] = {}

    def do_GET(self):
        if not type(self).license_endpoint:
            self.send_error(501)
            return
        body = json.dumps({"required": type(self).license_required}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        type(self).last_headers = dict(self.headers)
        body = json.dumps(
            {"id": "prj_test123", "name": "t", "environment": "local", "api_key": "cxr_abc"}
        ).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def api_server():
    _Handler.status = 201  # class-level state must not leak between tests
    _Handler.last_headers = {}
    _Handler.license_required = True
    _Handler.license_endpoint = True
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _Handler
    server.shutdown()
    thread.join(timeout=5)


class _NonTTY:
    def isatty(self) -> bool:
        return False


def test_flag_license_wins(monkeypatch):
    monkeypatch.setenv("CODEXRAY_LICENSE_KEY", "env-key")
    assert cli._resolve_license("flag-key") == "flag-key"


def test_env_license_fallback(monkeypatch):
    monkeypatch.setenv("CODEXRAY_LICENSE_KEY", "env-key")
    assert cli._resolve_license("") == "env-key"


def test_non_tty_without_key_exits_none(monkeypatch, capsys):
    monkeypatch.delenv("CODEXRAY_LICENSE_KEY", raising=False)
    monkeypatch.setattr(cli.sys, "stdin", _NonTTY())
    assert cli._resolve_license("") is None
    assert "--license" in capsys.readouterr().out


def test_empty_box_entry_exits_none(monkeypatch, capsys):
    monkeypatch.delenv("CODEXRAY_LICENSE_KEY", raising=False)

    class _TTY(_NonTTY):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdin", _TTY())
    monkeypatch.setattr(cli, "_prompt_license_box", lambda: "")
    assert cli._resolve_license("") is None
    assert "exiting" in capsys.readouterr().out


def test_box_prompt_draws_frame(capsys, monkeypatch):
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "typed-key")
    assert cli._prompt_license_box() == "typed-key"
    out = capsys.readouterr().out
    assert "CodeXRay — license required" in out
    assert out.count("+") >= 4  # box corners drawn


def test_create_project_sends_license_header(api_server):
    url, handler = api_server
    cli._create_project(url, "proj", "cxrl_mine")
    assert handler.last_headers.get("X-License-Key") == "cxrl_mine"


def test_create_project_omits_header_without_license(api_server):
    url, handler = api_server
    cli._create_project(url, "proj")
    assert "X-License-Key" not in handler.last_headers


def test_cmd_init_invalid_license_exits_1(api_server, monkeypatch, tmp_path, capsys):
    url, handler = api_server
    handler.status = 401
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CODEXRAY_LICENSE_KEY", raising=False)
    rc = cli.main(["init", "--api", url, "--license", "bad-key"])
    assert rc == 1
    assert "invalid license key" in capsys.readouterr().out
    assert not (tmp_path / cli.CONFIG_FILE).exists()


def test_cmd_init_valid_license_writes_config(api_server, monkeypatch, tmp_path, capsys):
    url, handler = api_server
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["init", "--api", url, "--license", "good-key", "--name", "demo"])
    assert rc == 0
    cfg = json.loads((tmp_path / cli.CONFIG_FILE).read_text())
    assert cfg["project_id"] == "prj_test123"
    assert cfg["api_key"] == "cxr_abc"
    assert "cxrl" not in json.dumps(cfg), "license must never be persisted"
    assert handler.last_headers.get("X-License-Key") == "good-key"


def test_api_env_supplies_default_url(api_server, monkeypatch, tmp_path):
    url, handler = api_server
    handler.license_required = False
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEXRAY_API", url)
    monkeypatch.delenv("CODEXRAY_LICENSE_KEY", raising=False)
    assert cli.main(["init", "--name", "envtest"]) == 0
    cfg = json.loads((tmp_path / cli.CONFIG_FILE).read_text())
    assert cfg["api_url"] == url


def test_open_server_skips_prompt(api_server, monkeypatch, tmp_path):
    url, handler = api_server
    handler.license_required = False
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CODEXRAY_LICENSE_KEY", raising=False)
    monkeypatch.setattr(cli.sys, "stdin", _NonTTY())
    monkeypatch.setattr(
        cli, "_resolve_license", lambda *_: pytest.fail("prompt must not run on open server")
    )
    assert cli.main(["init", "--api", url, "--name", "open"]) == 0
    assert "X-License-Key" not in handler.last_headers
    assert (tmp_path / cli.CONFIG_FILE).exists()


def test_gated_server_non_tty_requires_flag(api_server, monkeypatch, tmp_path, capsys):
    url, handler = api_server
    handler.license_required = True
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CODEXRAY_LICENSE_KEY", raising=False)
    monkeypatch.setattr(cli.sys, "stdin", _NonTTY())
    assert cli.main(["init", "--api", url]) == 1
    assert "--license" in capsys.readouterr().out
    assert not (tmp_path / cli.CONFIG_FILE).exists()


def test_license_probe_failure_falls_back(api_server, monkeypatch, tmp_path):
    url, handler = api_server
    handler.license_endpoint = False  # 501 → unknown, resolve normally
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CODEXRAY_LICENSE_KEY", raising=False)
    assert cli.main(["init", "--api", url, "--license", "fallback-key"]) == 0
    assert handler.last_headers.get("X-License-Key") == "fallback-key"
