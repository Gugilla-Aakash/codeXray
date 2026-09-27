"""CodeXRay API — FastAPI application (PRD §14, §21, §28)."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import ai as ai_engine
from . import byok as byok_engine
from . import config as app_config
from . import graph as graph_engine
from . import ingest, logingest, models, replay, schemas
from .db import get_session, init_db
from .schemas import (
    GraphOut,
    IncidentOut,
    IngestResult,
    LogOut,
    ProjectCreated,
    ProjectOut,
    ReplayOut,
    RootCauseOut,
    SpanOut,
    TraceOut,
    TraceSummary,
)
from .security import (
    RateLimiter,
    generate_api_key,
    hash_key,
    license_authorized,
    rate_limiter,
)
from .seed import build_demo_events, build_pulse_events
from .stream import manager

log = logging.getLogger("codexray.pulse")


def _ingest_commit(
    db: Session, project: models.Project, items: list[tuple[int, dict]]
) -> dict:
    """Blocking ingest+commit — always run via run_in_threadpool/asyncio.to_thread
    so the event loop (health, WS, pulse) stays responsive under load."""
    result = ingest.process_events(db, project, items)
    db.commit()
    return result


def _logs_commit(
    db: Session, project: models.Project, items: list[tuple[int, schemas.LogLineIn]]
) -> dict:
    result = logingest.process_logs(db, project, items)
    db.commit()
    return result


async def _demo_pulse_loop() -> None:
    """Healthy-traffic heartbeat for demo projects (DEMO_PULSE=1).

    Ingests one tiny all-success trace per demo project every few seconds so
    the event feed moves, req/min ticks, and the graph feels live during a
    walkthrough. Never creates incidents (success-only spans).
    """
    from .db import SessionLocal

    while True:
        await asyncio.sleep(3.0)
        try:
            db = SessionLocal()
            try:
                projects = db.scalars(
                    select(models.Project)
                    .where(models.Project.environment == "demo")
                    .order_by(desc(models.Project.created_at))
                    .limit(3)
                ).all()
                for project in projects:
                    tag = f"pulse{time.time_ns() % 10**14}"
                    events = build_pulse_events(tag)
                    result = await asyncio.to_thread(
                        _ingest_commit, db, project, list(enumerate(events))
                    )
                    for msg in result.pop("broadcasts"):
                        await manager.broadcast(project.id, msg)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("demo pulse failed")

ai_rate_limiter = RateLimiter(per_minute=app_config.AI_RATE_LIMIT_PER_MIN)
@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    pulse_task: asyncio.Task | None = None
    if app_config.DEMO_PULSE:
        pulse_task = asyncio.create_task(_demo_pulse_loop())
    yield
    if pulse_task is not None:
        pulse_task.cancel()
        try:
            await pulse_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="CodeXRay API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # hackathon MVP; restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- auth (PRD §28: project isolation via API keys) ----------

def get_project(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_session),
) -> models.Project:
    # API key via header only — never a query parameter, so secrets cannot
    # end up in access logs, proxies, or browser history.
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing API key")
    project = db.scalar(
        select(models.Project).where(models.Project.api_key_hash == hash_key(x_api_key))
    )
    if project is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    return project


def require_project_path(project_id: str, project: models.Project) -> models.Project:
    if project.id != project_id:
        raise HTTPException(status_code=403, detail="project mismatch")
    return project


license_fail_limiter = RateLimiter(per_minute=app_config.LICENSE_RATE_LIMIT_PER_MIN)


def require_license(
    request: Request,
    x_license_key: str | None = Header(default=None, alias="X-License-Key"),
) -> None:
    """SaaS license gate — reads config.LICENSE_KEYS at request time so tests
    (and future hot-reload) can change the set without re-importing the app.
    Empty set => open mode. Failed attempts are rate-limited per client IP."""
    if license_authorized(x_license_key, app_config.LICENSE_KEYS):
        return
    ip = request.client.host if request.client else "unknown"
    if not license_fail_limiter.allowed(ip):
        raise HTTPException(
            status_code=429,
            detail="Too many license attempts — try again shortly.",
        )
    raise HTTPException(status_code=401, detail="invalid or missing license key")


@app.get("/api/license")
def license_status() -> dict:
    """Public: lets clients know whether project creation needs a license key."""
    return {"required": bool(app_config.LICENSE_KEYS)}


# ---------- projects ----------

@app.post("/api/projects", response_model=ProjectCreated, status_code=201)
def create_project(
    body: schemas.ProjectCreate,
    db: Session = Depends(get_session),
    _license: None = Depends(require_license),
):
    plain, digest = generate_api_key()
    project = models.Project(
        id="prj_" + secrets.token_hex(4),
        name=body.name,
        environment=body.environment,
        api_key_hash=digest,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectCreated(
        id=project.id,
        name=project.name,
        environment=project.environment,
        created_at=project.created_at,
        api_key=plain,
    )


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(
    project: models.Project = Depends(get_project),
):
    # Tenant isolation: a key sees exactly its own project — never the fleet.
    return [
        ProjectOut(
            id=project.id,
            name=project.name,
            environment=project.environment,
            created_at=project.created_at,
        )
    ]


# ---------- telemetry ingestion ----------

@app.post("/api/telemetry", response_model=IngestResult)
async def post_telemetry(
    request: Request,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    if not rate_limiter.allowed(project.api_key_hash):
        return JSONResponse(status_code=429, content={"detail": "telemetry rate limit exceeded"})
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if isinstance(payload, dict) and "events" in payload and isinstance(payload["events"], list):
        raw = list(enumerate(payload["events"]))
    elif isinstance(payload, list):
        raw = list(enumerate(payload))
    elif isinstance(payload, dict):
        raw = [(0, payload)]
    else:
        raise HTTPException(status_code=400, detail="body must be an event, event list, or {events: [...]}")

    result = await run_in_threadpool(
        _ingest_commit,
        db,
        project,
        [(i, e if isinstance(e, dict) else {}) for i, e in raw],
    )
    for msg in result.pop("broadcasts"):
        await manager.broadcast(project.id, msg)
    return IngestResult(**result)


# ---------- log ingestion (`codexray logs` file tail) ----------

@app.post("/api/logs", response_model=IngestResult)
async def post_logs(
    body: schemas.LogsIn,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    if not rate_limiter.allowed("logs:" + project.api_key_hash):
        return JSONResponse(status_code=429, content={"detail": "log rate limit exceeded"})
    items = list(enumerate(body.lines))
    result = await run_in_threadpool(_logs_commit, db, project, items)
    for msg in result.pop("broadcasts"):
        await manager.broadcast(project.id, msg)
    return IngestResult(**result)


@app.get("/api/projects/{project_id}/logs", response_model=list[LogOut])
def list_logs(
    project_id: str,
    level: str | None = None,
    limit: int = 200,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    require_project_path(project_id, project)
    q = (
        select(models.LogRecord)
        .where(models.LogRecord.project_id == project.id)
        .order_by(desc(models.LogRecord.id))
        .limit(max(1, min(limit, 1000)))
    )
    if level:
        q = q.where(models.LogRecord.level == logingest.normalize_level(level))
    return [
        LogOut(
            id=r.id,
            ts=r.ts,
            level=r.level,
            service=r.service,
            message=r.message,
            source_file=r.source_file,
            received_at=r.received_at,
        )
        for r in db.scalars(q).all()
    ]


# ---------- graph / traces (PRD §21) ----------

@app.get("/api/projects/{project_id}/graph", response_model=GraphOut)
def get_graph(
    project_id: str,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    require_project_path(project_id, project)
    return graph_engine.build_graph(db, project.id)


@app.get("/api/projects/{project_id}/traces", response_model=list[TraceSummary])
def list_traces(
    project_id: str,
    status: str | None = None,
    limit: int = 50,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    require_project_path(project_id, project)
    q = (
        select(models.Trace, func.count(models.Span.id))
        .outerjoin(models.Span, models.Span.trace_id == models.Trace.id)
        .where(models.Trace.project_id == project.id)
        .group_by(models.Trace.id)
        .order_by(desc(models.Trace.start_time))
        .limit(max(1, min(limit, 200)))
    )
    if status:
        q = q.where(models.Trace.status == status)
    return [
        TraceSummary(
            trace_id=t.id,
            start_time=t.start_time,
            duration_ms=t.duration_ms,
            status=t.status,
            root_service=t.root_service,
            span_count=n,
        )
        for t, n in db.execute(q).all()
    ]


def _trace_out(db: Session, trace: models.Trace) -> TraceOut:
    spans = (
        db.scalars(
            select(models.Span)
            .where(models.Span.trace_id == trace.id)
            .order_by(models.Span.start_time)
        ).all()
    )
    return TraceOut(
        trace_id=trace.id,
        project_id=trace.project_id,
        start_time=trace.start_time,
        duration_ms=trace.duration_ms,
        status=trace.status,
        root_service=trace.root_service,
        spans=[
            SpanOut(
                span_id=s.id,
                parent_span_id=s.parent_span_id,
                service=s.service_name,
                operation=s.operation,
                timestamp=s.start_time,
                duration_ms=s.duration_ms,
                status=s.status,
                error=(
                    {"type": s.error_type, "message": s.error_message}
                    if s.error_message or s.error_type
                    else None
                ),
                request=s.request or {},
                response=s.response or {},
                metadata=s.meta or {},
            )
            for s in spans
        ],
    )


@app.get("/api/traces/{trace_id}", response_model=TraceOut)
def get_trace(
    trace_id: str,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    trace = db.get(models.Trace, trace_id)
    if trace is None or trace.project_id != project.id:
        raise HTTPException(status_code=404, detail="trace not found")
    return _trace_out(db, trace)


# ---------- incidents + replay ----------

def _incident_out(inc: models.Incident) -> IncidentOut:
    rc = inc.root_cause or {}
    root = (
        RootCauseOut(
            service=rc.get("service", ""),
            reason=rc.get("reason", ""),
            confidence=int(rc.get("confidence", 50)),
            propagation=list(rc.get("propagation", [])),
            span_id=rc.get("span_id"),
            signals=list(rc.get("signals") or []),
        )
        if isinstance(rc, dict) and rc.get("service")
        else rc
    )
    return IncidentOut(
        incident_id=inc.incident_id,
        trace_id=inc.trace_id,
        title=inc.title,
        severity=inc.severity,
        timestamp=inc.timestamp,
        status=inc.status,
        root_cause=root,
        affected_services=list(inc.affected_services or []),
    )


def _incident_or_404(db: Session, project: models.Project, incident_id: str) -> models.Incident:
    pk = models.Incident.parse_incident_id(incident_id)
    if pk is None:
        raise HTTPException(status_code=404, detail="incident not found")
    inc = db.get(models.Incident, pk)
    if inc is None or inc.project_id != project.id:
        raise HTTPException(status_code=404, detail="incident not found")
    return inc


@app.get("/api/projects/{project_id}/incidents", response_model=list[IncidentOut])
def list_incidents(
    project_id: str,
    status: str | None = None,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    require_project_path(project_id, project)
    q = (
        select(models.Incident)
        .where(models.Incident.project_id == project.id)
        .order_by(desc(models.Incident.timestamp))
    )
    if status:
        q = q.where(models.Incident.status == status)
    return [_incident_out(i) for i in db.scalars(q).all()]


@app.get("/api/incidents/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: str,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    return _incident_out(_incident_or_404(db, project, incident_id))


@app.get("/api/incidents/{incident_id}/replay", response_model=ReplayOut)
def replay_incident(
    incident_id: str,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    inc = _incident_or_404(db, project, incident_id)
    trace = db.get(models.Trace, inc.trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    spans = db.scalars(
        select(models.Span).where(models.Span.trace_id == trace.id)
    ).all()
    dicts = [
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
    return ReplayOut(
        incident_id=inc.incident_id,
        trace_id=trace.id,
        actions=replay.build_actions(dicts),
    )


# ---------- AI incident summary (Groq, generic for any project) ----------

def _span_dicts(db: Session, trace_id: str, include_io: bool = False) -> list[dict]:
    rows = db.scalars(select(models.Span).where(models.Span.trace_id == trace_id)).all()
    out = []
    for s in rows:
        row = {
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
        if include_io:
            # BYOK investigation context only; the summary stays compact.
            row["request"] = s.request or {}
            row["response"] = s.response or {}
            row["metadata"] = s.meta or {}
        out.append(row)
    return out


def _ai_context_for_incident(
    db: Session, inc: models.Incident
) -> tuple[dict, list[dict], dict | None, list[dict]]:
    """Return (trace_dict, span_dicts, root_cause_dict, error_actions) for any incident."""
    trace = db.get(models.Trace, inc.trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    span_dicts = _span_dicts(db, trace.id)
    rc = inc.root_cause if isinstance(inc.root_cause, dict) else {}
    trace_dict = {
        "trace_id": trace.id,
        "root_service": trace.root_service,
        "status": trace.status,
        "duration_ms": trace.duration_ms,
    }
    err_actions = [
        a for a in replay.build_actions(span_dicts) if a.get("action") in ("ERROR", "RETRY")
    ]
    return trace_dict, span_dicts, (rc or None), err_actions


@app.post("/api/incidents/{incident_id}/ai-summary", response_model=schemas.AiSummaryOut)
async def ai_summary(
    incident_id: str,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    if not ai_engine.is_enabled():
        raise HTTPException(status_code=503, detail="AI not configured on server (GROQ_API_KEY missing)")
    if not ai_rate_limiter.allowed("ai:" + project.api_key_hash):
        return JSONResponse(status_code=429, content={"detail": "AI rate limit exceeded — wait a minute"})
    inc = _incident_or_404(db, project, incident_id)
    # Serve cache: same incident, any project — summaries are deterministic-ish
    # and cheap to reuse. `force` is intentionally absent in MVP.
    if inc.ai_summary:
        return schemas.AiSummaryOut(
            incident_id=inc.incident_id,
            trace_id=inc.trace_id,
            summary=inc.ai_summary,
            model=app_config.GROQ_MODEL,
            cached=True,
            generated_at=inc.ai_summary_at or inc.timestamp,
        )
    trace_dict, span_dicts, rc, err_actions = _ai_context_for_incident(db, inc)
    ctx = ai_engine.build_incident_context(trace_dict, span_dicts, rc, err_actions)
    try:
        text, model = await ai_engine.call_groq(ai_engine.summary_messages(ctx))
    except ai_engine.AIError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from None
    inc.ai_summary = text
    inc.ai_summary_at = ai_engine.now()
    db.commit()
    return schemas.AiSummaryOut(
        incident_id=inc.incident_id,
        trace_id=inc.trace_id,
        summary=text,
        model=model,
        cached=False,
        generated_at=inc.ai_summary_at,
    )


# ---------- BYOK AI investigation (LiteLLM, user's own key) ----------
# Cost boundary: the summary above spends CodeXRay's Groq budget; everything
# below runs on the caller's provider key (held in memory, short TTL) and the
# provider is chosen explicitly, so e.g. Kimi traffic is never sent to OpenAI.

byok_rate_limiter = RateLimiter(per_minute=app_config.BYOK_RATE_LIMIT_PER_MIN)


def _byok_guard(project: models.Project, bucket: str = "byok") -> None:
    if not byok_rate_limiter.allowed(f"{bucket}:" + project.api_key_hash):
        raise HTTPException(status_code=429, detail="AI rate limit exceeded — wait a minute")


def _investigation_context(db: Session, project: models.Project, incident_id: str) -> tuple[dict, models.Incident]:
    inc = _incident_or_404(db, project, incident_id)
    trace = db.get(models.Trace, inc.trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    spans = _span_dicts(db, trace.id, include_io=True)
    incident_dict = {
        "incident_id": inc.incident_id,
        "title": inc.title,
        "severity": inc.severity,
        "status": inc.status,
        "root_cause": inc.root_cause if isinstance(inc.root_cause, dict) else {},
        "affected_services": inc.affected_services or [],
    }
    trace_dict = {
        "trace_id": trace.id,
        "root_service": trace.root_service,
        "status": trace.status,
        "duration_ms": trace.duration_ms,
    }
    ctx = byok_engine.build_investigation_context(incident_dict, trace_dict, spans, inc.ai_summary)
    return ctx, inc


@app.get("/api/projects/{project_id}/ai/providers")
def list_ai_providers(
    project_id: str,
    project: models.Project = Depends(get_project),
):
    require_project_path(project_id, project)
    return {"providers": byok_engine.providers_public()}


@app.post("/api/projects/{project_id}/ai/providers/test", response_model=schemas.ProviderTestOut)
async def test_ai_provider(
    project_id: str,
    body: schemas.ProviderTestIn,
    project: models.Project = Depends(get_project),
):
    require_project_path(project_id, project)
    _byok_guard(project, "byok-test")
    try:
        return await byok_engine.test_connection(
            body.provider, body.model, body.api_key, body.base_url
        )
    except byok_engine.ByokError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": str(e)}) from None


@app.post("/api/projects/{project_id}/ai/connections", response_model=schemas.ConnectionOut)
async def create_ai_connection(
    project_id: str,
    body: schemas.ConnectionIn,
    project: models.Project = Depends(get_project),
):
    require_project_path(project_id, project)
    _byok_guard(project, "byok-test")
    # Validate before storing: a bad key never becomes a connection.
    try:
        await byok_engine.test_connection(
            body.provider, body.model, body.api_key, body.base_url
        )
    except byok_engine.ByokError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": str(e)}) from None
    conn = byok_engine.connections.create(
        project.id, body.provider, body.model, body.api_key, body.base_url
    )
    return schemas.ConnectionOut(connection_id=conn.id, provider=conn.provider, model=conn.model, base_url=conn.base_url)


@app.delete("/api/projects/{project_id}/ai/connections/{connection_id}", status_code=204)
def delete_ai_connection(
    project_id: str,
    connection_id: str,
    project: models.Project = Depends(get_project),
):
    require_project_path(project_id, project)
    byok_engine.connections.drop(project.id, connection_id)


def _byok_error(e: byok_engine.ByokError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": str(e)})


@app.post("/api/projects/{project_id}/ai/investigate", response_model=schemas.InvestigateOut)
async def investigate(
    project_id: str,
    body: schemas.InvestigateIn,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    require_project_path(project_id, project)
    _byok_guard(project)
    try:
        conn = byok_engine.connections.get(project.id, body.connection_id)
    except byok_engine.ByokError as e:
        raise _byok_error(e) from None
    ctx, _ = _investigation_context(db, project, body.incident_id)
    history = [t.model_dump() for t in body.history]
    try:
        res = await byok_engine.complete(conn, ctx, body.message, history)
    except byok_engine.ByokError as e:
        raise _byok_error(e) from None
    return schemas.InvestigateOut(
        answer=res["answer"],
        provider=res["provider"],
        model=res["model"],
        usage=res["usage"],
    )


@app.post("/api/projects/{project_id}/ai/investigate/stream")
async def investigate_stream(
    project_id: str,
    body: schemas.InvestigateIn,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    require_project_path(project_id, project)
    _byok_guard(project)
    try:
        conn = byok_engine.connections.get(project.id, body.connection_id)
    except byok_engine.ByokError as e:
        raise _byok_error(e) from None
    ctx, _ = _investigation_context(db, project, body.incident_id)
    history = [t.model_dump() for t in body.history]

    async def events():
        async for ev in byok_engine.stream(conn, ctx, body.message, history):
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ---------- demo seed ----------

def _demo_seed_blocking(db: Session, project: models.Project, tag: str) -> dict:
    """Wipe + seed (blocking) — runs in a worker thread."""
    # Repeatable demo: wipe this project's telemetry first so fixed demo
    # IDs never collide with a previous seed.
    db.execute(
        models.Incident.__table__.delete().where(
            models.Incident.project_id == project.id
        )
    )
    db.execute(
        models.Span.__table__.delete().where(
            models.Span.trace_id.in_(
                select(models.Trace.id).where(models.Trace.project_id == project.id)
            )
        )
    )
    db.execute(
        models.Trace.__table__.delete().where(models.Trace.project_id == project.id)
    )
    for svc in db.scalars(
        select(models.Service).where(models.Service.project_id == project.id)
    ).all():
        svc.status = "healthy"
    safe_tag = "".join(c if c.isalnum() or c in "-_" else "-" for c in tag) or f"run{int(time.time())}"
    events = build_demo_events(tag=safe_tag)
    return _ingest_commit(db, project, list(enumerate(events)))


async def _run_demo_seed(db: Session, project: models.Project, tag: str = "") -> IngestResult:
    """Wipe + seed the demo checkout story, broadcast over WS.

    Shared by /demo/seed (repeatable) and the one-click /api/demo/setup.
    """
    result = await run_in_threadpool(_demo_seed_blocking, db, project, tag)
    for msg in result.pop("broadcasts"):
        await manager.broadcast(project.id, msg)
    return IngestResult(**result)


@app.post("/api/projects/{project_id}/demo/seed", response_model=IngestResult)
async def seed_demo(
    project_id: str,
    tag: str = Query(default="", max_length=32),
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    require_project_path(project_id, project)
    return await _run_demo_seed(db, project, tag)


# ⚡ Inject failure: roll a fresh failing checkout trace into the project so
# a live demo can show the incident appearing in real time (deck's 6-step
# story). Auth via API key, flag-gated (DEMO_SETUP), per-project rate limit.
demo_inject_limiters: dict[str, RateLimiter] = {}


@app.post("/api/projects/{project_id}/demo/inject", response_model=IngestResult)
async def demo_inject(
    project_id: str,
    project: models.Project = Depends(get_project),
    db: Session = Depends(get_session),
):
    require_project_path(project_id, project)
    if not app_config.DEMO_SETUP:
        raise HTTPException(status_code=404, detail="not found")
    limiter = demo_inject_limiters.setdefault(project.id, RateLimiter(per_minute=8))
    if not limiter.allowed(project.id):
        raise HTTPException(
            status_code=429, detail="Slow down — wait a moment before injecting again."
        )
    # Unique tag each time so span/trace IDs never collide; land the failure
    # in the last ~3s so timestamps read as "just now".
    tag = f"fail{time.time_ns() % 10**14}"
    events = build_demo_events(base_ts=time.time() - 13.5, tag=tag, incident_only=True)
    result = await run_in_threadpool(
        _ingest_commit, db, project, list(enumerate(events))
    )
    for msg in result.pop("broadcasts"):
        await manager.broadcast(project.id, msg)
    return IngestResult(**result)


# One-click demo project: create + seed in a single call so a first-time
# visitor never has to curl. Flag-gated (DEMO_SETUP) and rate-limited.
# Set DEMO_SETUP=0 in production.
demo_setup_limiter = RateLimiter(per_minute=10)


@app.post("/api/demo/setup", response_model=ProjectCreated, status_code=201)
async def demo_setup(
    db: Session = Depends(get_session),
    _license: None = Depends(require_license),
):
    if not app_config.DEMO_SETUP:
        raise HTTPException(status_code=404, detail="not found")
    if not demo_setup_limiter.allowed("demo-setup"):
        raise HTTPException(status_code=429, detail="Too many demo setups — try again in a minute.")
    plain, digest = generate_api_key()
    project = models.Project(
        id="prj_" + secrets.token_hex(4),
        name="Demo · Checkout",
        environment="demo",
        api_key_hash=digest,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    await _run_demo_seed(db, project)
    return ProjectCreated(
        id=project.id,
        name=project.name,
        environment=project.environment,
        created_at=project.created_at,
        api_key=plain,
    )


# ---------- live stream (PRD WS transport) ----------

@app.websocket("/api/projects/{project_id}/stream")
async def stream_project(websocket: WebSocket, project_id: str):
    from .db import SessionLocal

    # Auth rides the Sec-WebSocket-Protocol header: the key never appears in
    # the URL (access logs, proxies, Referer) and the handshake round-trip
    # costs nothing extra. Client offers ["codexray.v1", "<key>"]; we require
    # the fixed token, validate the cxr_ element, and echo only the fixed
    # token — never the secret.
    offered = [
        part.strip()
        for part in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if part.strip()
    ]
    key = None
    if "codexray.v1" in offered:
        key = next((part for part in offered if part.startswith("cxr_")), None)

    db = SessionLocal()
    try:
        project = None
        if key:
            project = db.scalar(
                select(models.Project).where(models.Project.api_key_hash == hash_key(key))
            )
        if project is None or project.id != project_id:
            await websocket.close(code=4401)
            return
        await websocket.accept(subprotocol="codexray.v1")
        await manager.connect(project.id, websocket)
        await websocket.send_json({"type": "connected", "project_id": project.id})
        try:
            while True:
                await websocket.receive_text()  # heartbeat / keep-alive
        except Exception:
            pass
        finally:
            manager.disconnect(project.id, websocket)
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/supabase/health")
def supabase_health_check():
    from .supabase_client import supabase_health

    return supabase_health()
