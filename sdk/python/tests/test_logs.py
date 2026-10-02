"""codexray-sdk — log tail tests (stdlib only, stub API)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from codexray.logtail import (
    LogTailer,
    normalize_level,
    parse_line,
    resolve_targets,
    ship_lines,
    sniff_level,
)


class StubAPI:
    def __init__(self) -> None:
        self.batches: list[list[dict]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.batches.append(body.get("lines", []))
                resp = b'{"accepted": 1, "rejected": []}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *a: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def lines(self) -> list[dict]:
        out: list[dict] = []
        for b in self.batches:
            out.extend(b)
        return out

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def stub():
    s = StubAPI()
    yield s
    s.close()


def test_level_helpers():
    assert normalize_level("WARNING") == "warn"
    assert normalize_level("FATAL") == "error"
    assert normalize_level("weird") == "info"
    assert sniff_level("ERROR: disk full") == "error"
    assert sniff_level("hello world") == "info"


def test_parse_plain_and_jsonl():
    plain = parse_line("2026-01-01 WARN slow query", "a.log", "svc")
    assert plain is not None
    assert plain["level"] == "warn"
    assert plain["service"] == "svc"

    js = parse_line(
        json.dumps({"level": "error", "message": "boom", "service": "payments"}),
        "b.jsonl",
        "fallback",
    )
    assert js is not None
    assert js["level"] == "error"
    assert js["message"] == "boom"
    assert js["service"] == "payments"

    assert parse_line("   \n", "c.log", "s") is None


def test_tail_appends_and_partial_lines(tmp_path: Path):
    f = tmp_path / "app.log"
    f.write_text("existing\n")
    tailer = LogTailer(f, service="svc", from_start=True, poll=0.01)
    first = tailer.poll_once()
    assert [x["message"] for x in first] == ["existing"]

    # nothing new
    assert tailer.poll_once() == []

    # append complete line
    with f.open("a") as fh:
        fh.write("second\n")
    batch = tailer.poll_once()
    assert [x["message"] for x in batch] == ["second"]

    # partial line: not yielded until newline arrives
    with f.open("a") as fh:
        fh.write("partial")
    assert tailer.poll_once() == []
    with f.open("a") as fh:
        fh.write("-done\n")
    batch = tailer.poll_once()
    assert [x["message"] for x in batch] == ["partial-done"]


def test_tail_default_starts_at_eof(tmp_path: Path):
    f = tmp_path / "app.log"
    f.write_text("old line\n")
    tailer = LogTailer(f, service="svc", from_start=False, poll=0.01)
    assert tailer.poll_once() == []
    with f.open("a") as fh:
        fh.write("new line\n")
    batch = tailer.poll_once()
    assert [x["message"] for x in batch] == ["new line"]


def test_tail_rotation_resets(tmp_path: Path):
    f = tmp_path / "rot.log"
    f.write_text("aaa\nbbb\n")
    tailer = LogTailer(f, service="svc", from_start=True, poll=0.01)
    assert len(tailer.poll_once()) == 2

    # simulate truncate/rotate: shrink the file, then write fresh content
    f.write_text("ccc\n")
    batch = tailer.poll_once()
    assert [x["message"] for x in batch] == ["ccc"]


def test_directory_targets_and_symlink_escape(tmp_path: Path):
    inside = tmp_path / "inbox"
    inside.mkdir()
    (inside / "a.log").write_text("x\n")
    (inside / "b.jsonl").write_text("{}\n")
    (inside / "ignore.md").write_text("no\n")
    (inside / "sub").mkdir()

    outside = tmp_path / "secret.log"
    outside.write_text("password=hunter2\n")
    link = inside / "escape.log"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")

    targets = resolve_targets(inside)
    names = {t.name for t in targets}
    assert "a.log" in names
    assert "b.jsonl" in names
    assert "escape.log" not in names, "symlink escaping root must be refused"
    assert "ignore.md" not in names


def test_ship_lines_posts_batch(stub: StubAPI):
    ok = ship_lines(stub.url, "cxr_key", [{"level": "info", "message": "hi"}])
    assert ok is True
    assert stub.lines[0]["message"] == "hi"


def test_ship_lines_never_raises_on_dead_api():
    assert ship_lines("http://127.0.0.1:1", "k", [{"message": "x"}], timeout=0.2) is False


def test_cli_logs_help():
    from codexray.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["logs", "--help"])
    assert exc.value.code == 0
