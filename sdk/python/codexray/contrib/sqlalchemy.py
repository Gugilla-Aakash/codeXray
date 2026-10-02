"""CodeXRay SDK — opt-in SQLAlchemy instrumentation (no monkeypatching).

CPython's sqlite3 types are immutable: cursor/connection methods cannot be
patched, so raw-sqlite auto-hooks are impossible. SQLAlchemy's event system
is the safe seam instead — one import, version-tolerant, zero app risk:

    from codexray.contrib.sqlalchemy import instrument_engine
    instrument_engine(engine)  # service="sqlite" by default
"""

from __future__ import annotations

from typing import Any

from ..patch import _child, _finish, _op_from_sql


def instrument_engine(engine: Any, service: str = "sqlite") -> Any:
    """Attach span listeners to a SQLAlchemy engine. Idempotent."""
    try:
        from sqlalchemy import event
    except ImportError:
        return engine
    if getattr(engine, "_cx_instrumented", False):
        return engine
    try:
        engine._cx_instrumented = True  # type: ignore[attr-defined]
    except Exception:
        pass

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any) -> None:
        try:
            context._cx_span = _child(_op_from_sql(statement), service)
        except Exception:
            pass

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any) -> None:
        span = getattr(context, "_cx_span", None)
        context._cx_span = None
        _finish(span)

    @event.listens_for(engine, "handle_error")
    def _error(context: Any) -> None:
        span = getattr(context, "_cx_span", None)
        context._cx_span = None
        exc = getattr(context, "original_exception", None) or getattr(context, "sqlalchemy_exception", None)
        _finish(
            span,
            "error",
            {"type": type(exc).__name__ if exc else "DBError", "message": str(exc)[:200] if exc else ""},
        )

    return engine
