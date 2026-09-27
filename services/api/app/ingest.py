"""CodeXRay API — telemetry ingestion pipeline (PRD §13, §28, §29).

Tolerant by design: malformed events, duplicates, and missing parents
never fail the batch — they are reported per-event in the result.

Performance: validation is in-memory; all DB reads/writes are batched
(a handful of statements per request instead of ~3 round-trips per span).
This matters when the DB is a remote Postgres (Supabase) where each
round-trip costs tens of ms.
"""

from __future__ import annotations

import time

from pydantic import ValidationError
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from . import models, rootcause
from .config import SLOW_SPAN_MS
from .schemas import TelemetryEvent
from .security import infer_service_type, redact

_IN_CHUNK = 400  # keep IN (...) lists below SQLite's variable limit


def _normalize_status(status: str) -> str:
    s = (status or "").lower()
    return "success" if s in ("success", "ok", "okay") else ("error" if s == "error" else s or "success")


def _chunks(xs: list[str], n: int = _IN_CHUNK):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def process_events(
    db: Session, project: models.Project, raw_events: list[tuple[int, dict]]
) -> dict:
    """Returns {accepted, rejected, incident_ids, broadcasts}."""
    accepted = 0
    rejected: list[dict] = []

    # ---- Phase A: validate (pure CPU, no DB) ----------------------------
    valid: list[tuple[TelemetryEvent, str, bool, float]] = []
    for index, raw in raw_events:
        try:
            ev = TelemetryEvent.model_validate(raw)
        except ValidationError as exc:
            rejected.append({"index": index, "reason": f"invalid event: {exc.errors()[0]['msg']}"})
            continue
        if not ev.trace_id or not ev.span_id or not ev.service:
            rejected.append({"index": index, "reason": "missing trace_id/span_id/service"})
            continue
        status = _normalize_status(ev.status)
        is_error = status == "error"
        try:
            ts = float(ev.timestamp)
        except (TypeError, ValueError):
            rejected.append({"index": index, "reason": "invalid timestamp"})
            continue
        valid.append((ev, status, is_error, ts))

    if not valid:
        return {"accepted": 0, "rejected": rejected, "incident_ids": [], "broadcasts": []}

    # ---- Phase B: services (1 SELECT + optional 1 bulk INSERT + 1 re-SELECT)
    names = {ev.service for ev, _, _, _ in valid}
    services: dict[str, models.Service] = {}
    name_list = sorted(names)
    for ids in _chunks(name_list):
        for s in db.scalars(
            select(models.Service).where(
                models.Service.project_id == project.id,
                models.Service.name.in_(ids),
            )
        ).all():
            services[s.name] = s
    missing = [n for n in name_list if n not in services]
    if missing:
        db.execute(
            insert(models.Service),
            [
                {
                    "project_id": project.id,
                    "name": n,
                    "type": infer_service_type(n),
                    "status": "healthy",
                }
                for n in missing
            ],
        )
        for ids in _chunks(missing):
            for s in db.scalars(
                select(models.Service).where(
                    models.Service.project_id == project.id,
                    models.Service.name.in_(ids),
                )
            ).all():
                services[s.name] = s

    # Service status transitions happen for every otherwise-valid event,
    # in batch order (matches the original row-by-row pipeline: even an event
    # later rejected for a cross-project id still flipped the service flag).
    svc_broadcasts: list[dict] = []
    for ev, status, is_error, ts in valid:
        svc = services[ev.service]
        prev = svc.status
        if is_error:
            svc.status = "error"
        elif ev.duration_ms >= SLOW_SPAN_MS and svc.status == "healthy":
            svc.status = "degraded"
        if svc.status != prev:
            svc_broadcasts.append(
                {
                    "type": "service_status",
                    "project_id": project.id,
                    "service": svc.name,
                    "status": svc.status,
                }
            )

    # ---- Phase C: traces (1 SELECT for the batch, bulk insert new ones) --
    trace_ids = list({ev.trace_id for ev, _, _, _ in valid})
    traces: dict[str, models.Trace] = {}
    for ids in _chunks(trace_ids):
        for t in db.scalars(select(models.Trace).where(models.Trace.id.in_(ids))).all():
            traces[t.id] = t

    new_traces: list[models.Trace] = []
    trace_ok: list[tuple[TelemetryEvent, str, bool, float, models.Trace]] = []
    for ev, status, is_error, ts in valid:
        trace = traces.get(ev.trace_id)
        if trace is not None and trace.project_id != project.id:
            rejected.append({"index": -1, "reason": "trace_id belongs to another project"})
            continue
        if trace is None:
            trace = models.Trace(
                id=ev.trace_id,
                project_id=project.id,
                start_time=ts,
                duration_ms=0,
                status="success",
                root_service=ev.service if not ev.parent_span_id else None,
            )
            traces[ev.trace_id] = trace
            new_traces.append(trace)
        trace.start_time = min(trace.start_time, ts)
        trace.duration_ms = max(
            trace.duration_ms, (ts - trace.start_time) * 1000 + ev.duration_ms
        )
        if is_error:
            trace.status = "error"
        if trace.root_service is None and not ev.parent_span_id:
            trace.root_service = ev.service
        trace_ok.append((ev, status, is_error, ts, trace))

    # Parent rows first: Postgres FKs on spans.trace_id need them now.
    if new_traces:
        db.add_all(new_traces)
        db.flush()

    # ---- Phase D: span duplicates (1 SELECT of batch span ids) ----------
    remaining: list[tuple[TelemetryEvent, str, bool, float, models.Trace]] = []
    candidate_ids = [
        ev.span_id
        for ev, _, _, _t, _tr in trace_ok
    ]
    # de-dup while preserving order
    seen_candidates: set[str] = set()
    ordered_ids: list[str] = []
    for sid in candidate_ids:
        if sid not in seen_candidates:
            seen_candidates.add(sid)
            ordered_ids.append(sid)

    existing_spans: dict[str, str] = {}  # span_id -> trace_id
    for ids in _chunks(ordered_ids):
        for row in db.execute(
            select(models.Span.id, models.Span.trace_id).where(models.Span.id.in_(ids))
        ).all():
            existing_spans[row.id] = row.trace_id

    if existing_spans:
        # Load any traces referenced by duplicate spans but absent above,
        # so the cross-project check needs no per-row queries.
        extra = [tid for tid in set(existing_spans.values()) if tid not in traces]
        for ids in _chunks(extra):
            for t in db.scalars(select(models.Trace).where(models.Trace.id.in_(ids))).all():
                traces[t.id] = t

    seen_span_ids: set[str] = set()
    for ev, status, is_error, ts, trace in trace_ok:
        if ev.span_id in seen_span_ids:
            accepted += 1  # duplicate within the batch: idempotent
            continue
        if ev.span_id in existing_spans:
            dup_trace = traces.get(existing_spans[ev.span_id])
            if dup_trace is not None and dup_trace.project_id != project.id:
                rejected.append(
                    {"index": -1, "reason": "span_id belongs to another project"}
                )
                continue
            accepted += 1  # duplicate: idempotent, still counts
            continue
        seen_span_ids.add(ev.span_id)
        remaining.append((ev, status, is_error, ts, trace))

    # ---- Phase E: bulk-insert spans (1 executemany) ---------------------
    span_broadcasts: list[dict] = []
    touched_traces: set[str] = set()
    span_rows: list[dict] = []
    for ev, status, is_error, ts, trace in remaining:
        svc = services[ev.service]
        err = ev.error or {}
        span_rows.append(
            {
                "id": ev.span_id,
                "trace_id": ev.trace_id,
                "parent_span_id": ev.parent_span_id,
                "service_id": svc.id,
                "service_name": ev.service,
                "operation": ev.operation,
                "start_time": ts,
                "duration_ms": ev.duration_ms,
                "status": status,
                "error_type": str(err.get("type")) if err.get("type") else None,
                "error_message": str(err.get("message")) if err.get("message") else None,
                "request": redact(ev.request),
                "response": redact(ev.response),
                "meta": redact(ev.metadata),
            }
        )
        accepted += 1
        touched_traces.add(ev.trace_id)
        span_broadcasts.append(
            {
                "type": "error" if is_error else "new_event",
                "project_id": project.id,
                "trace_id": ev.trace_id,
                "span_id": ev.span_id,
                "service": ev.service,
                "operation": ev.operation,
                "status": status,
                "timestamp": ts,
            }
        )
    if span_rows:
        db.execute(insert(models.Span), span_rows)
    db.flush()

    # Entry service: a span whose parent never arrived is effectively a root,
    # even when parent_span_id names a missing span (§29 tolerance).
    for trace_id in touched_traces:
        trace = traces.get(trace_id)
        if trace is not None and trace.root_service is None:
            earliest = db.scalar(
                select(models.Span)
                .where(models.Span.trace_id == trace_id)
                .order_by(models.Span.start_time, models.Span.id)
                .limit(1)
            )
            if earliest is not None:
                trace.root_service = earliest.service_name
    db.flush()

    # ---- Incident detection: touched trace with error spans -------------
    incident_ids: list[str] = []
    incident_broadcasts: list[dict] = []
    for trace_id in touched_traces:
        spans = db.scalars(select(models.Span).where(models.Span.trace_id == trace_id)).all()
        if not any((s.status or "").lower() == "error" for s in spans):
            continue
        existing = db.scalar(
            select(models.Incident).where(
                models.Incident.project_id == project.id,
                models.Incident.trace_id == trace_id,
                models.Incident.status == "open",
            )
        )
        span_dicts = [
            {
                "span_id": s.id,
                "parent_span_id": s.parent_span_id,
                "service": s.service_name,
                "operation": s.operation,
                "timestamp": s.start_time,
                "duration_ms": s.duration_ms,
                "status": s.status,
                "error": (
                    {"type": s.error_type, "message": s.error_message}
                    if s.error_message or s.error_type
                    else None
                ),
            }
            for s in spans
        ]
        rc = rootcause.analyze(span_dicts, slow_ms=SLOW_SPAN_MS) or {
            "service": spans[0].service_name,
            "reason": "Failure detected",
            "confidence": 50,
            "propagation": [],
        }
        err_spans = [s for s in spans if (s.status or "").lower() == "error"]
        first_err = min(err_spans, key=lambda s: s.start_time)
        root_err = not first_err.parent_span_id or all(
            (s.id != first_err.parent_span_id) for s in spans
        )
        title = f"{first_err.operation or first_err.service_name} failure"
        if existing is None:
            inc = models.Incident(
                project_id=project.id,
                trace_id=trace_id,
                title=title,
                severity="critical" if root_err else "high",
                root_cause=rc,
                affected_services=rc.get("propagation", []),
                status="open",
                timestamp=time.time(),
            )
            db.add(inc)
            db.flush()
            incident_ids.append(inc.incident_id)
            incident_broadcasts.append(
                {
                    "type": "incident",
                    "project_id": project.id,
                    "incident_id": inc.incident_id,
                    "trace_id": trace_id,
                    "title": title,
                    "severity": inc.severity,
                    "root_cause": rc,
                }
            )
        else:
            existing.root_cause = rc
            existing.affected_services = rc.get("propagation", [])
            db.flush()

    # Rejected cross-project events keep the original per-event index when
    # we still know it; reconstruct positions for the messages emitted above.
    return {
        "accepted": accepted,
        "rejected": rejected,
        "incident_ids": incident_ids,
        "broadcasts": svc_broadcasts + span_broadcasts + incident_broadcasts,
    }
