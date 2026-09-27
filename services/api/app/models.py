"""CodeXRay API — SQLAlchemy models (PRD §15 Data Model).

Column types are Postgres-compatible; the default dev database is SQLite
(see config.DATABASE_URL).
"""

from __future__ import annotations

import time

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now_ts() -> float:
    return time.time()


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), default="production")
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(16), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), default="service")
    status: Mapped[str] = mapped_column(String(16), default="healthy")
    # DB column is "metadata" (PRD §15); `metadata` is reserved on DeclarativeBase.
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # trace_id
    project_id: Mapped[str] = mapped_column(String(16), ForeignKey("projects.id"), index=True)
    start_time: Mapped[float] = mapped_column(Float, index=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="success", index=True)
    root_service: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # span_id
    trace_id: Mapped[str] = mapped_column(String(64), ForeignKey("traces.id"), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id"), index=True)
    service_name: Mapped[str] = mapped_column(String(128), index=True)  # denormalized
    operation: Mapped[str] = mapped_column(String(256), default="")
    start_time: Mapped[float] = mapped_column(Float, index=True)  # epoch seconds
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="success", index=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class LogRecord(Base):
    __tablename__ = "log_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(16), ForeignKey("projects.id"), index=True)
    ts: Mapped[float] = mapped_column(Float, default=now_ts, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    service: Mapped[str] = mapped_column(String(128), default="")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str] = mapped_column(String(512), default="")
    received_at: Mapped[float] = mapped_column(Float, default=now_ts)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(16), ForeignKey("projects.id"), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), ForeignKey("traces.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="high")
    root_cause: Mapped[dict] = mapped_column(JSON, default=dict)
    affected_services: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    timestamp: Mapped[float] = mapped_column(Float, default=now_ts, index=True)
    # Cached Groq summary (generic per incident, any project). Nullable so
    # pre-AI rows keep working; filled on first POST .../ai-summary.
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    ai_summary_at: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)

    @property
    def incident_id(self) -> str:
        return f"INC-{1000 + self.id}"

    @staticmethod
    def parse_incident_id(incident_id: str) -> int | None:
        try:
            kind, num = incident_id.split("-", 1)
            if kind != "INC":
                return None
            pk = int(num) - 1000
            return pk if pk > 0 else None
        except (ValueError, AttributeError):
            return None
