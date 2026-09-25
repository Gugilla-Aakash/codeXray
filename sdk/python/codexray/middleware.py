"""CodeXRay SDK — pure-ASGI middleware (no framework dependency).

Wraps any ASGI app (FastAPI, Starlette, Django Channels, raw ASGI):
one trace per HTTP request, error capture, health/docs noise excluded.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, MutableMapping

from . import naming, patch
from .tracer import Tracer, set_default_tracer

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
ASGIApp = Callable[[Scope, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]], Awaitable[None]]

SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi", "/favicon", "/_next", "/static")


class _UpstreamParent:
    """Adapter letting tracer.span() adopt a browser-side parent span."""

    def __init__(self, trace_id: str, span_id: str) -> None:
        self.trace_id = trace_id
        self.span_id = span_id


def _upstream_parent(trace_id: str | None, span_id: str | None) -> _UpstreamParent | None:
    if trace_id and span_id:
        return _UpstreamParent(trace_id, span_id)
    return None


class CodeXRayMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        tracer: Tracer,
        service: str | None = None,
        exclude_prefixes: tuple[str, ...] = SKIP_PREFIXES,
        split_services: bool = False,
        autopatch: bool = True,
    ) -> None:
        self.app = app
        self.tracer = tracer
        self.service = service or tracer.service
        self.exclude = exclude_prefixes
        self.split_services = split_services
        set_default_tracer(tracer)
        if autopatch:
            try:
                patch.install()
            except Exception:
                pass

    async def __call__(self, scope: Scope, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith(self.exclude):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        incoming = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers", [])
            if isinstance(k, (bytes, bytearray))
        }
        upstream_trace = incoming.get("x-codexray-trace")
        upstream_parent = incoming.get("x-codexray-parent")
        svc = naming.service_for_path(self.service, path) if self.split_services else self.service
        with self.tracer.span(
            f"{method} {path}",
            service=svc,
            parent=_upstream_parent(upstream_trace, upstream_parent),
            metadata={"query": scope.get("query_string", b"").decode("latin1")[:200]},
            as_current=True,
        ) as span:
            status_code = 500
            try:
                async def send_wrapper(message: Message) -> None:
                    nonlocal status_code
                    if message.get("type") == "http.response.start":
                        status_code = int(message.get("status", 200))
                        headers = list(message.get("headers", []))
                        headers.append(
                            (b"x-codexray-trace", span.trace_id.encode("latin1"))
                        )
                        message["headers"] = headers
                    await send(message)

                await self.app(scope, receive, send_wrapper)
            except Exception as exc:
                span.finish(
                    status="error",
                    error={"type": type(exc).__name__, "message": str(exc)[:300]},
                )
                raise
            else:
                span.finish(status="error" if status_code >= 500 else "success")
