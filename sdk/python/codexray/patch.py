"""CodeXRay SDK — fail-silent auto-instrumentation (stdlib + stdlib-style).

Patches, per process, the libraries every Python backend funnels through:

- httpx sync + async clients  -> one span per outbound call
- http.client (urllib + anything on it) + urllib3/requests if present
- (sqlite: see codexray.contrib.sqlalchemy — sqlite3 types are immutable
  and cannot be monkeypatched; the event-based helper covers SQLAlchemy,
  the dominant real-world path)

Rules this module lives by:

- install-time failures skip that target; call-time failures fall back
  to the original call. Telemetry — including this module — must never
  break the app.
- already-wrapped callables are never wrapped twice (reinstall-safe).
- the sender's own HTTP is invisible (see tracer.sending): no
  self-tracing feedback loop.
"""

from __future__ import annotations

import functools
import http.client
from typing import Any

from . import naming
from .tracer import Span, _new_id, current_span, default_tracer, is_sending

_originals: list[tuple[Any, str, Any]] = []


def _remember(obj: Any, attr: str, orig: Any) -> None:
    if not any(o is obj and a == attr for o, a, _ in _originals):
        _originals.append((obj, attr, orig))


def _restore_all() -> None:
    while _originals:
        obj, attr, orig = _originals.pop()
        try:
            setattr(obj, attr, orig)
        except Exception:
            continue


def _swap(obj: Any, attr: str, wrapper: Any) -> bool:
    """Install wrapper unless already ours. Returns True when installed."""
    try:
        if getattr(getattr(obj, attr), "_cx_wrapped", False):
            return True
        orig = getattr(obj, attr)
        wrapper = functools.wraps(orig)(wrapper)
    except Exception:
        try:
            orig = getattr(obj, attr)
        except Exception:
            return False
    try:
        wrapper._cx_wrapped = True  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        setattr(obj, attr, wrapper)
    except Exception:
        return False
    _remember(obj, attr, orig)
    return True


def _child(operation: str, service: str, metadata: dict | None = None) -> Span | None:
    t = default_tracer()
    if t is None:
        return None
    parent = current_span()
    return Span(
        t,
        trace_id=parent.trace_id if parent else _new_id(),
        parent_span_id=parent.span_id if parent else None,
        service=service,
        operation=operation,
        metadata=metadata or {},
    )


def _finish(span: Span | None, status: str = "success", error: dict | None = None) -> None:
    try:
        if span is not None:
            span.finish(status=status, error=error)
    except Exception:
        pass


def _op_from_sql(sql: Any) -> str:
    try:
        first = str(sql).lstrip().split(None, 1)[0].upper()
    except Exception:
        return "SQL"
    return f"SQL {first}" if first.isalpha() else "SQL"


def _patch_httpx() -> list[str]:
    try:
        import httpx
    except ImportError:
        return []
    done: list[str] = []

    try:
        orig_send = httpx.Client.send

        def send(self: Any, request: Any, **kw: Any) -> Any:
            if is_sending():
                return orig_send(self, request, **kw)
            url = getattr(request, "url", None)
            host = str(getattr(url, "host", "") or "")
            span = _child(
                f"{getattr(request, 'method', 'GET')} {getattr(url, 'path', '/')}",
                naming.service_for_host(host),
                {"url": str(url)[:200]},
            )
            if span is None:
                return orig_send(self, request, **kw)
            try:
                resp = orig_send(self, request, **kw)
            except Exception as exc:
                _finish(span, "error", {"type": type(exc).__name__, "message": str(exc)[:200]})
                raise
            code = int(getattr(resp, "status_code", 200) or 200)
            span.metadata["status_code"] = code
            _finish(span, "error" if code >= 500 else "success")
            return resp

        if _swap(httpx.Client, "send", send):
            done.append("httpx.Client.send")
    except Exception:
        pass

    try:
        orig_asend = httpx.AsyncClient.send

        async def asend(self: Any, request: Any, **kw: Any) -> Any:
            if is_sending():
                return await orig_asend(self, request, **kw)
            url = getattr(request, "url", None)
            host = str(getattr(url, "host", "") or "")
            span = _child(
                f"{getattr(request, 'method', 'GET')} {getattr(url, 'path', '/')}",
                naming.service_for_host(host),
                {"url": str(url)[:200]},
            )
            if span is None:
                return await orig_asend(self, request, **kw)
            try:
                resp = await orig_asend(self, request, **kw)
            except Exception as exc:
                _finish(span, "error", {"type": type(exc).__name__, "message": str(exc)[:200]})
                raise
            code = int(getattr(resp, "status_code", 200) or 200)
            span.metadata["status_code"] = code
            _finish(span, "error" if code >= 500 else "success")
            return resp

        if _swap(httpx.AsyncClient, "send", asend):
            done.append("httpx.AsyncClient.send")
    except Exception:
        pass
    return done


def _wrap_http_connection(cls: Any, label: str) -> list[str]:
    done: list[str] = []
    try:
        orig_request = cls.request

        def request(self: Any, method: str, url: str, *a: Any, **k: Any) -> Any:
            if is_sending():
                return orig_request(self, method, url, *a, **k)
            stale = getattr(self, "_cx_span", None)
            if stale is not None:
                _finish(stale)
                self._cx_span = None
            host = str(getattr(self, "host", "") or "")
            path = url.split("?", 1)[0] if isinstance(url, str) else "/"
            span = _child(f"{method} {path}", naming.service_for_host(host), {"url": str(url)[:200]})
            if span is None:
                return orig_request(self, method, url, *a, **k)
            self._cx_span = span
            try:
                return orig_request(self, method, url, *a, **k)
            except Exception as exc:
                self._cx_span = None
                _finish(span, "error", {"type": type(exc).__name__, "message": str(exc)[:200]})
                raise

        if _swap(cls, "request", request):
            done.append(f"{label}.request")
    except Exception:
        pass

    try:
        orig_getresponse = cls.getresponse

        def getresponse(self: Any, *a: Any, **k: Any) -> Any:
            span = getattr(self, "_cx_span", None)
            self._cx_span = None
            try:
                resp = orig_getresponse(self, *a, **k)
            except Exception as exc:
                _finish(span, "error", {"type": type(exc).__name__, "message": str(exc)[:200]})
                raise
            if span is not None:
                code = int(getattr(resp, "status", 200) or 200)
                span.metadata["status_code"] = code
                _finish(span, "error" if code >= 500 else "success")
            return resp

        if _swap(cls, "getresponse", getresponse):
            done.append(f"{label}.getresponse")
    except Exception:
        pass
    return done


def _patch_http_client() -> list[str]:
    done = _wrap_http_connection(http.client.HTTPConnection, "http.client.HTTPConnection")
    # HTTPSConnection inherits request/getresponse: patching the base covers
    # it. urllib3/requests override them, so patch those too when present.
    try:
        import urllib3.connection as u3c

        done += _wrap_http_connection(u3c.HTTPConnection, "urllib3.HTTPConnection")
        done += _wrap_http_connection(u3c.HTTPSConnection, "urllib3.HTTPSConnection")
    except ImportError:
        pass
    return done


def _patch_sqlite() -> list[str]:
    # Deliberately a no-op: CPython sqlite3 types are immutable, so their
    # methods cannot be monkeypatched. Use codexray.contrib.sqlalchemy
    # (event-based, safe) instead. Kept as a named step for reporting.
    return []


def install() -> list[str]:
    """Install all available auto-patches. Returns what stuck. Never raises."""
    done: list[str] = []
    for fn in (_patch_httpx, _patch_http_client, _patch_sqlite):
        try:
            done.extend(fn())
        except Exception:
            continue
    return done


def uninstall() -> None:
    try:
        _restore_all()
    except Exception:
        pass
