"""CodeXRay API — pydantic schemas (PRD §12, §16, §17, §19, §21)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .security import validate_base_url


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="production", max_length=64)


class ProjectOut(BaseModel):
    id: str
    name: str
    environment: str
    created_at: float


class ProjectCreated(ProjectOut):
    api_key: str


class TelemetryEvent(BaseModel):
    """PRD §16 telemetry event contract. Unknown fields ignored (tolerance)."""

    model_config = ConfigDict(extra="ignore")

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    service: str
    operation: str = ""
    timestamp: float
    duration_ms: float = 0
    status: str = "success"
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class RejectedEvent(BaseModel):
    index: int
    reason: str


class IngestResult(BaseModel):
    accepted: int
    rejected: list[RejectedEvent] = Field(default_factory=list)
    incident_ids: list[str] = Field(default_factory=list)


class LogLineIn(BaseModel):
    """One tailed log line from `codexray logs`. Unknown fields ignored."""

    model_config = ConfigDict(extra="ignore")

    level: str = Field(default="info", max_length=16)
    # Empty allowed at the schema layer so one blank line is a per-line
    # reject, not a 422 that fails the whole batch (tolerance §29).
    message: str = Field(default="", max_length=4000)
    service: str = Field(default="", max_length=128)
    source_file: str = Field(default="", max_length=512)
    ts: float | None = None


class LogsIn(BaseModel):
    lines: list[LogLineIn] = Field(default_factory=list, max_length=500)


class LogOut(BaseModel):
    id: int
    ts: float
    level: str
    service: str
    message: str
    source_file: str
    received_at: float


class GraphNode(BaseModel):
    id: str
    name: str
    type: str
    status: str
    request_count: int = 0


class GraphEdge(BaseModel):
    source: str
    target: str
    request_count: int = 0
    error_rate: float = 0.0
    avg_latency: float = 0.0


class GraphSummary(BaseModel):
    services: int = 0
    healthy: int = 0
    degraded: int = 0
    failing: int = 0
    requests_per_min: float = 0.0
    error_rate: float = 0.0
    p95_latency: float = 0.0


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    summary: GraphSummary


class SpanOut(BaseModel):
    span_id: str
    parent_span_id: str | None
    service: str
    operation: str
    timestamp: float
    duration_ms: float
    status: str
    error: dict[str, Any] | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceOut(BaseModel):
    trace_id: str
    project_id: str
    start_time: float
    duration_ms: float
    status: str
    root_service: str | None
    spans: list[SpanOut] = Field(default_factory=list)


class TraceSummary(BaseModel):
    trace_id: str
    start_time: float
    duration_ms: float
    status: str
    root_service: str | None
    span_count: int


class RootCauseOut(BaseModel):
    service: str
    reason: str
    confidence: int
    propagation: list[str] = Field(default_factory=list)
    span_id: str | None = None
    signals: list[str] = Field(default_factory=list)


class IncidentOut(BaseModel):
    incident_id: str
    trace_id: str
    title: str
    severity: str
    timestamp: float
    status: str
    root_cause: RootCauseOut | dict[str, Any]
    affected_services: list[str] = Field(default_factory=list)


class ReplayAction(BaseModel):
    time: float
    action: Literal[
        "START_REQUEST",
        "ENTER_SERVICE",
        "CALL_DEPENDENCY",
        "RETURN_RESPONSE",
        "ERROR",
        "RETRY",
        "END_REQUEST",
    ]
    service: str
    message: str | None = None


class ReplayOut(BaseModel):
    incident_id: str
    trace_id: str
    actions: list[ReplayAction]


class AiSummaryOut(BaseModel):
    incident_id: str
    trace_id: str
    summary: str
    model: str
    cached: bool = False
    generated_at: float


# ---------- BYOK AI investigation (LiteLLM) ----------
# Request bodies accept camelCase (AI-PLAN contract) and snake_case alike;
# responses serialize camelCase (FastAPI response_model_by_alias default).
# User provider keys are marked repr=False so they never appear in logs.

class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ProviderTestIn(_Camel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=512, alias="apiKey", repr=False)
    base_url: str | None = Field(default=None, max_length=512, alias="baseUrl")

    @field_validator("base_url")
    @classmethod
    def _guard_base_url(cls, v: str | None) -> str | None:
        # SSRF guard at the edge — BaseUrlError subclasses ValueError, so
        # pydantic turns it into a 422 with a user-safe message.
        if v and v.strip():
            validate_base_url(v.strip())
        return v


class ConnectionIn(ProviderTestIn):
    """Connect = validate + store; same fields as a connection test."""


class ConnectionOut(_Camel):
    connection_id: str = Field(alias="connectionId")
    provider: str
    model: str
    base_url: str | None = Field(default=None, alias="baseUrl")


class ProviderTestOut(_Camel):
    success: bool
    provider: str
    model: str
    base_url: str | None = Field(default=None, alias="baseUrl")


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class InvestigateIn(_Camel):
    connection_id: str = Field(min_length=1, max_length=128, alias="connectionId")
    incident_id: str = Field(min_length=1, max_length=16, alias="incidentId")
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=24)


class InvestigateOut(_Camel):
    answer: str
    provider: str
    model: str
    usage: dict[str, Any] = Field(default_factory=dict)
