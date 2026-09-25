"""CodeXRay SDK — tracer and background sender (stdlib only)."""

from __future__ import annotations

import contextvars
import json
import queue
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager
from typing import Any, Iterator


def _new_id(n: int = 12) -> str:
    return uuid.uuid4().hex[:n]


# Process-wide default tracer for auto-instrumented libraries that have no
# handle to the app's tracer (httpx/urllib/sqlite hooks). Set by the
# middleware / `serve`; unset means "no tracing backend" (hooks stay silent).
_default_tracer: "Tracer | None" = None


def set_default_tracer(tracer: "Tracer | None") -> None:
    global _default_tracer
    _default_tracer = tracer


def default_tracer() -> "Tracer | None":
    return _default_tracer


# Reentrancy guard: the sender's own HTTP call must never be traced
# (otherwise every flush would spawn a span about itself).
_send_state = threading.local()


def is_sending() -> bool:
    return bool(getattr(_send_state, "active", False))


class sending:
    def __enter__(self) -> None:
        _send_state.active = True

    def __exit__(self, *exc: Any) -> None:
        _send_state.active = False


# Request-scoped parent: middleware sets the root span here so nested
# `tracer.span()` calls anywhere in the call tree attach automatically.
_current_span: contextvars.ContextVar["Span | None"] = contextvars.ContextVar(
    "codexray_span", default=None
)


def current_span() -> "Span | None":
    """The ambient parent span for this request/task, if any."""
    return _current_span.get()


class Tracer:
    """Creates spans and ships them to the CodeXRay API in the background.

    Never raises into your app: every network/serialization failure is
    swallowed after one silent retry drop.
    """

    def __init__(
        self,
        service: str,
        api_url: str,
        api_key: str,
        flush_interval: float = 2.0,
        batch_size: int = 20,
        timeout: float = 3.0,
    ) -> None:
        self.service = service
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.flush_interval = flush_interval
        self.batch_size = batch_size
        self.timeout = timeout
        self._queue: queue.Queue[dict] = queue.Queue()
        self._stop = threading.Event()
        self._mu = threading.Lock()
        # One opener per tracer: building the default opener creates an SSL
        # context (cert scan, ~100ms+), which must not happen per-send —
        # it loses thread races and wastes the flush cadence.
        self._opener = urllib.request.build_opener()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            batch = [first]
            while len(batch) < self.batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            with self._mu:
                self._send(batch)

    def _send(self, events: list[dict]) -> None:
        try:
            req = urllib.request.Request(
                f"{self.api_url}/api/telemetry",
                data=json.dumps({"events": events}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self.api_key,
                },
                method="POST",
            )
            with sending():
                with self._opener.open(req, timeout=self.timeout):
                    pass
        except Exception:
            pass  # telemetry must never break the app

    def enqueue(self, event: dict) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            pass

    def flush(self, timeout: float = 5.0) -> None:
        """Best-effort synchronous flush (tests, shutdown)."""
        buf: list[dict] = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                buf.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if buf:
            with self._mu:
                self._send(buf)

    def close(self, timeout: float = 15.0) -> None:
        """Flush everything and wait for the worker: after close returns,
        every enqueued event has been delivered (or its send failed)."""
        self.flush()
        self._stop.set()
        self._worker.join(timeout=timeout)

    def start_trace(self, operation: str, service: str | None = None) -> "Span":
        return Span(
            self,
            trace_id=_new_id(),
            parent_span_id=None,
            service=service or self.service,
            operation=operation,
        )

    @contextmanager
    def span(
        self,
        operation: str,
        service: str | None = None,
        parent: "Span | None" = None,
        metadata: dict[str, Any] | None = None,
        as_current: bool = False,
    ) -> Iterator["Span"]:
        """Child span; inherits the ambient request span unless a parent is
        given. With as_current=True the new span becomes ambient itself.
        """
        ambient = _current_span.get()
        link = parent if parent is not None else ambient
        s = Span(
            self,
            trace_id=link.trace_id if link else _new_id(),
            parent_span_id=link.span_id if link else None,
            service=service or self.service,
            operation=operation,
            metadata=metadata,
        )
        token = None
        if as_current:
            token = _current_span.set(s)
        try:
            yield s
        except Exception as exc:
            s.finish(status="error", error={"type": type(exc).__name__, "message": str(exc)[:300]})
            raise
        else:
            s.finish()
        finally:
            if token is not None:
                _current_span.reset(token)


class Span:
    def __init__(
        self,
        tracer: Tracer,
        trace_id: str,
        parent_span_id: str | None,
        service: str,
        operation: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.tracer = tracer
        self.trace_id = trace_id
        self.span_id = _new_id(16)
        self.parent_span_id = parent_span_id
        self.service = service
        self.operation = operation
        self.metadata = metadata or {}
        self.start = time.time()
        self._done = False

    def finish(
        self,
        status: str = "success",
        error: dict[str, Any] | None = None,
    ) -> None:
        if self._done:
            return
        self._done = True
        self.tracer.enqueue(
            {
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "service": self.service,
                "operation": self.operation,
                "timestamp": self.start,
                "duration_ms": round((time.time() - self.start) * 1000, 1),
                "status": status,
                "error": error,
                "metadata": self.metadata,
            }
        )
