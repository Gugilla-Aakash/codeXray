"""CodeXRay API — database engine/session (PRD §15).

SQLite by default; Supabase Postgres (psycopg + NullPool on the pooler)
when DATABASE_URL points there. See config.py.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL, USE_NULL_POOL


class Base(DeclarativeBase):
    pass


_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False}
if USE_NULL_POOL:
    _kwargs["poolclass"] = NullPool

engine = create_engine(
    DATABASE_URL, future=True, echo=os.getenv("SQL_ECHO") == "1", **_kwargs
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(bind=engine)
    _ensure_ai_columns()


def _ensure_ai_columns() -> None:
    """Lightweight migration: add incidents.ai_summary* on pre-AI databases.

    create_all() never alters existing tables, so dev DBs created before the
    AI feature would otherwise crash on SELECT/INSERT of the new columns.
    Works on SQLite and Postgres (ADD COLUMN IF NOT EXISTS is Postgres-only,
    so inspect first for portability).
    """
    try:
        from sqlalchemy import inspect, text

        cols = {c["name"] for c in inspect(engine).get_columns("incidents")}
        with engine.begin() as conn:
            if "ai_summary" not in cols:
                conn.execute(text("ALTER TABLE incidents ADD COLUMN ai_summary TEXT"))
            if "ai_summary_at" not in cols:
                conn.execute(text("ALTER TABLE incidents ADD COLUMN ai_summary_at FLOAT"))
    except Exception:
        # init must never crash the app (e.g. fresh DB race in tests).
        pass


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
