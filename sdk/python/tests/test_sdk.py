"""codexray-sdk tests — stdlib stub server, no backend dependency."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from codexray.middleware import CodeXRayMiddleware
from codexray.tracer import Tracer


class Stub:
    def __init__(self) -> None:
        self.received: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _reply(self) -> None:
                body = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                outer.received.append(json.loads(self.rfile.read(length) or b"{}"))
                self._reply()

            def do_GET(self) -> None:
                self._reply()

            def log_message(self, *a: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def events(self) -> list[dict]:
        out: list[dict] = []
        for body in self.received:
            out.extend(body.get("events", []))
        return out

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def stub():
    s = Stub()
    yield s
    s.close()


def test_span_finish_ships_event(stub: Stub) -> None:
    t = Tracer(service="svc", api_url=stub.url, api_key="k", flush_interval=60)
    with t.span("op", metadata={"a": 1}):
        pass
    t.flush()
    t.close()
    evs = stub.events()
    assert len(evs) == 1
    assert evs[0]["service"] == "svc"
    assert evs[0]["operation"] == "op"
    assert evs[0]["status"] == "success"
    assert evs[0]["duration_ms"] >= 0


def test_span_error_captured(stub: Stub) -> None:
    t = Tracer(service="svc", api_url=stub.url, api_key="k", flush_interval=60)
    with pytest.raises(ValueError), t.span("boom"):
        raise ValueError("kaput")
    t.flush()
    t.close()
    evs = stub.events()
    assert evs[0]["status"] == "error"
    assert evs[0]["error"]["type"] == "ValueError"


def test_sender_never_raises() -> None:
    t = Tracer(service="svc", api_url="http://127.0.0.1:9", api_key="k", flush_interval=60)
    with t.span("op"):
        pass
    t.flush()  # connection refused → swallowed
    t.close()


def _run(app, path="/x", headers=None) -> tuple[int, dict]:
    status: dict = {}
    body: list[bytes] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            status["code"] = msg["status"]
            status["headers"] = dict(msg.get("headers", []))
        elif msg["type"] == "http.response.body":
            body.append(msg.get("body", b""))

    import asyncio

    raw = [(k.encode() if isinstance(k, str) else k, v.encode() if isinstance(v, str) else v) for k, v in (headers or [])]
    asyncio.run(app({"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": raw}, receive, send))
    return status.get("code", 0), status.get("headers", {})


def test_middleware_traces_request(stub: Stub) -> None:
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    t = Tracer(service="gram", api_url=stub.url, api_key="k", flush_interval=60)
    wrapped = CodeXRayMiddleware(inner, t)
    code, headers = _run(wrapped, "/assistant/analyze")
    assert code == 200
    assert headers.get(b"x-codexray-trace")
    t.flush()
    t.close()
    evs = stub.events()
    assert len(evs) == 1
    assert evs[0]["operation"] == "GET /assistant/analyze"
    assert evs[0]["service"] == "gram"


def test_nested_spans_inherit_ambient_parent(stub: Stub) -> None:
    from codexray import current_span

    t = Tracer(service="api", api_url=stub.url, api_key="k", flush_interval=60)
    assert current_span() is None
    with t.span("request", as_current=True) as root:
        assert current_span() is root
        with t.span("db query", service="postgres"):
            pass
        assert current_span() is root
    assert current_span() is None
    t.flush()
    t.close()
    evs = {e["operation"]: e for e in stub.events()}
    assert evs["db query"]["parent_span_id"] == evs["request"]["span_id"]
    assert evs["db query"]["trace_id"] == evs["request"]["trace_id"]


def test_middleware_marks_500_and_skips_health(stub: Stub) -> None:
    async def boom(scope, receive, send):
        raise RuntimeError("db down")

    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    t = Tracer(service="gram", api_url=stub.url, api_key="k", flush_interval=60)
    import asyncio

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        pass

    try:
        asyncio.run(
            CodeXRayMiddleware(boom, t)(
                {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []},
                receive,
                send,
            )
        )
    except RuntimeError:
        pass
    asyncio.run(
        CodeXRayMiddleware(ok, t)(
            {"type": "http", "method": "GET", "path": "/health", "query_string": b"", "headers": []},
            receive,
            send,
        )
    )
    t.flush()
    t.close()
    evs = stub.events()
    assert len(evs) == 1  # error span only; /health skipped
    assert evs[0]["status"] == "error"
    assert evs[0]["error"]["type"] == "RuntimeError"


def test_middleware_continues_browser_trace(stub: Stub) -> None:
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    t = Tracer(service="api", api_url=stub.url, api_key="k", flush_interval=60)
    wrapped = CodeXRayMiddleware(inner, t)
    code, _ = _run(
        wrapped,
        "/api/items",
        headers=[(b"x-codexray-trace", b"browsertrace1234"), (b"x-codexray-parent", b"browserspan5678")],
    )
    assert code == 200
    t.flush()
    t.close()
    evs = stub.events()
    assert len(evs) == 1
    assert evs[0]["trace_id"] == "browsertrace1234"
    assert evs[0]["parent_span_id"] == "browserspan5678"


def test_naming_host_map() -> None:
    from codexray.naming import service_for_host, service_for_path
    assert service_for_host("api.github.com") == "github-api"
    assert service_for_host("sub.api.github.com") == "github-api"
    assert service_for_host("generativelanguage.googleapis.com") == "gemini"
    assert service_for_host("api.groq.com") == "groq"
    assert service_for_host("overpass-api.de") == "overpass"
    assert service_for_host("overpass.kumi.systems") == "overpass"
    assert service_for_host("api.stripe.com") == "stripe"
    assert service_for_host("api.foo.com") == "foo"
    assert service_for_host("") == "http"

    assert service_for_path("svc", "/api/v1/search") == "svc-search"
    assert service_for_path("svc", "/api/v1/analyze/status/42784cf8-2396-4a87") == "svc-analyze-status"
    assert service_for_path("svc", "/api/v1/items/12345") == "svc-items"
    assert service_for_path("svc", "/assistant/datasets/x") == "svc-assistant-datasets"
    assert service_for_path("svc", "/health") == "svc-health"
    assert service_for_path("svc", "/") == "svc"


def _patched(stub: Stub):
    from codexray import patch, set_default_tracer
    from codexray.tracer import Tracer

    t = Tracer(service="app", api_url=stub.url, api_key="k", flush_interval=60)
    set_default_tracer(t)
    installed = patch.install()
    assert installed, "expected at least one patch to install"
    return t


def _unpatched() -> None:
    from codexray import patch, set_default_tracer

    patch.uninstall()
    set_default_tracer(None)


def test_autopatch_httpx_and_urllib(stub: Stub) -> None:
    httpx = pytest.importorskip("httpx")
    import urllib.request

    t = _patched(stub)
    try:
        with t.span("request", as_current=True):
            httpx.Client().get(stub.url + "/v1/things")
            urllib.request.urlopen(stub.url + "/plain", timeout=5).read()
    finally:
        t.flush()
        t.close()
        _unpatched()
    evs = {e["operation"]: e for e in stub.events()}
    assert "GET /v1/things" in evs
    assert evs["GET /v1/things"]["parent_span_id"] == evs["request"]["span_id"]
    assert "GET /plain" in evs


def test_autopatch_sqlite(stub: Stub) -> None:
    pytest.importorskip("sqlalchemy")
    from codexray.contrib.sqlalchemy import instrument_engine
    from sqlalchemy import create_engine, text

    t = _patched(stub)
    try:
        engine = instrument_engine(create_engine("sqlite://"))
        with t.span("request", as_current=True) as root, engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (a TEXT)"))
            conn.execute(text("INSERT INTO t VALUES ('x')"))
    finally:
        t.flush()
        t.close()
        _unpatched()
    evs = stub.events()
    ops = [e["operation"] for e in evs]
    assert "SQL CREATE" in ops
    assert "SQL INSERT" in ops
    assert all(e["service"] == "sqlite" for e in evs if e["operation"].startswith("SQL"))
    root_id = next(e["span_id"] for e in evs if e["operation"] == "request")
    assert all(e["parent_span_id"] == root_id for e in evs if e["operation"].startswith("SQL"))


def test_scan_finds_routes_and_deps(tmp_path) -> None:
    from codexray.scan import report, scan

    (tmp_path / "app.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/search')\n"
        "def search(): ...\n"
        "@router.post('/analyze/{name}')\n"
        "def analyze(): ...\n"
        "import httpx, groq\n"
    )
    (tmp_path / "plain.py").write_text("x = 1\n")
    result = scan(tmp_path)
    assert result.files_scanned == 2
    by_path = {r.path: r.method for r in result.routes}
    assert by_path == {"/search": "GET", "/analyze/{name}": "POST"}
    assert sorted(result.deps) == ["groq", "http"]
    assert "routes: 2" in report(result)


def test_autopatch_is_silent_without_tracer(stub: Stub) -> None:
    import sqlite3

    from codexray import patch as patch_mod

    installed = patch_mod.install()
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE q (a TEXT)")  # no tracer: pure passthrough
        assert stub.events() == []
    finally:
        patch_mod.uninstall()
