"use client";

/* Typed client for the CodeXRay FastAPI backend (PRD §21).
   API base is overridable via NEXT_PUBLIC_CODEXRAY_API for deploys. */

export const API_BASE =
  process.env.NEXT_PUBLIC_CODEXRAY_API ?? "http://127.0.0.1:3101";

export type GraphNode = {
  id: string;
  name: string;
  type: string;
  status: string;
  request_count: number;
};

export type GraphEdge = {
  source: string;
  target: string;
  request_count: number;
  error_rate: number;
  avg_latency: number;
};

export type GraphSummary = {
  services: number;
  healthy: number;
  degraded: number;
  failing: number;
  requests_per_min: number;
  error_rate: number;
  p95_latency: number;
};

export type Graph = { nodes: GraphNode[]; edges: GraphEdge[]; summary: GraphSummary };

export type Span = {
  span_id: string;
  parent_span_id: string | null;
  service: string;
  operation: string;
  timestamp: number;
  duration_ms: number;
  status: string;
  error: { type?: string; message?: string } | null;
  request: Record<string, unknown>;
  response: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type Trace = {
  trace_id: string;
  project_id: string;
  start_time: number;
  duration_ms: number;
  status: string;
  root_service: string | null;
  spans: Span[];
};

export type TraceSummary = {
  trace_id: string;
  start_time: number;
  duration_ms: number;
  status: string;
  root_service: string | null;
  span_count: number;
};

export type RootCause = {
  service: string;
  reason: string;
  confidence: number;
  propagation: string[];
  span_id?: string | null;
  signals?: string[];
};

export type Incident = {
  incident_id: string;
  trace_id: string;
  title: string;
  severity: string;
  timestamp: number;
  status: string;
  root_cause: RootCause | Record<string, unknown>;
  affected_services: string[];
};

export type LogLine = {
  id: number;
  ts: number;
  level: "debug" | "info" | "warn" | "error";
  service: string;
  message: string;
  source_file: string;
  received_at: number;
};

export type ReplayAction = {
  time: number;
  action:
    | "START_REQUEST"
    | "ENTER_SERVICE"
    | "CALL_DEPENDENCY"
    | "RETURN_RESPONSE"
    | "ERROR"
    | "RETRY"
    | "END_REQUEST";
  service: string;
  message: string | null;
};

export type AiSummary = {
  incident_id: string;
  trace_id: string;
  summary: string;
  model: string;
  cached: boolean;
  generated_at: number;
};

/* ---- BYOK AI investigation (LiteLLM) ---- */

export type AiProvider = {
  id: string;
  label: string;
  models: string[];
  baseUrlEditable: boolean;
  requiresBaseUrl: boolean;
  defaultBaseUrl: string | null;
  note: string;
};

export type ConnectionInfo = {
  connectionId: string;
  provider: string;
  model: string;
  baseUrl: string | null;
};

export type ConnectionResult = {
  success: boolean;
  provider: string;
  model: string;
  baseUrl: string | null;
};

export type ChatTurn = { role: "user" | "assistant"; content: string };

export type InvestigationAnswer = {
  answer: string;
  provider: string;
  model: string;
  usage: Record<string, number | null>;
};

export type StreamDone = { provider: string; model: string; durationMs?: number; ttftMs?: number };

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function detailToError(status: number, body: unknown, fallback: string): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return new ApiError(status, detail);
  if (detail && typeof detail === "object") {
    const d = detail as { code?: unknown; message?: unknown };
    return new ApiError(
      status,
      typeof d.message === "string" ? d.message : fallback,
      typeof d.code === "string" ? d.code : undefined
    );
  }
  return new ApiError(status, fallback);
}

export async function api<T>(path: string, key: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "X-API-Key": key, ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw detailToError(res.status, body, res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const endpoints = {
  graph: (pid: string) => api<Graph>(`/api/projects/${pid}/graph`, getKey()),
  traces: (pid: string) => api<TraceSummary[]>(`/api/projects/${pid}/traces?limit=50`, getKey()),
  trace: (tid: string) => api<Trace>(`/api/traces/${tid}`, getKey()),
  incidents: (pid: string) => api<Incident[]>(`/api/projects/${pid}/incidents`, getKey()),
  logs: (pid: string, level?: string) =>
    api<LogLine[]>(
      `/api/projects/${pid}/logs?limit=200${level ? `&level=${level}` : ""}`,
      getKey()
    ),
  demoInject: (pid: string) =>
    api<{ accepted: number; rejected: number; incident_ids: string[] }>(
      `/api/projects/${pid}/demo/inject`,
      getKey(),
      { method: "POST" }
    ),
  replay: (iid: string) => api<{ incident_id: string; trace_id: string; actions: ReplayAction[] }>(
    `/api/incidents/${iid}/replay`,
    getKey()
  ),
  aiSummary: (iid: string) =>
    api<AiSummary>(`/api/incidents/${iid}/ai-summary`, getKey(), { method: "POST" }),
  aiProviders: (pid: string) =>
    api<{ providers: AiProvider[] }>(`/api/projects/${pid}/ai/providers`, getKey()),
  aiTestProvider: (
    pid: string,
    body: { provider: string; model: string; apiKey: string; baseUrl?: string | null }
  ) =>
    api<ConnectionResult>(`/api/projects/${pid}/ai/providers/test`, getKey(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  aiConnect: (
    pid: string,
    body: { provider: string; model: string; apiKey: string; baseUrl?: string | null }
  ) =>
    api<ConnectionInfo>(`/api/projects/${pid}/ai/connections`, getKey(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  aiDisconnect: (pid: string, cid: string) =>
    api<void>(`/api/projects/${pid}/ai/connections/${cid}`, getKey(), { method: "DELETE" }),
  aiInvestigate: (
    pid: string,
    body: { connectionId: string; incidentId: string; message: string; history: ChatTurn[] }
  ) =>
    api<InvestigationAnswer>(`/api/projects/${pid}/ai/investigate`, getKey(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

/* SSE-over-POST: the investigate stream is a POST, so EventSource won't do.
   We read the fetch body ourselves and dispatch parsed events. */
export async function streamInvestigate(
  pid: string,
  body: { connectionId: string; incidentId: string; message: string; history: ChatTurn[] },
  handlers: {
    onDelta: (text: string) => void;
    onDone: (info: StreamDone) => void;
    onError: (err: { code: string; message: string }) => void;
  },
  signal?: AbortSignal
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/projects/${pid}/ai/investigate/stream`, {
      method: "POST",
      headers: { "X-API-Key": getKey(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    handlers.onError({ code: "network_error", message: "Could not reach the API." });
    return;
  }
  if (!res.ok || !res.body) {
    const parsed = await res.json().catch(() => ({}));
    const err = detailToError(res.status, parsed, "Investigation failed to start.");
    handlers.onError({ code: err.code ?? "request_failed", message: err.message });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const frames = buf.split("\n\n");
      buf = frames.pop() ?? "";
      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        let ev: {
          type?: string;
          text?: string;
          code?: string;
          message?: string;
          provider?: string;
          model?: string;
          durationMs?: number;
          ttftMs?: number;
        };
        try {
          ev = JSON.parse(payload);
        } catch {
          continue;
        }
        if (ev.type === "delta" && ev.text) handlers.onDelta(ev.text);
        else if (ev.type === "done")
          handlers.onDone({
            provider: ev.provider ?? "",
            model: ev.model ?? "",
            durationMs: ev.durationMs,
            ttftMs: ev.ttftMs,
          });
        else if (ev.type === "error")
          handlers.onError({
            code: ev.code ?? "provider_error",
            message: ev.message ?? "Investigation failed.",
          });
      }
    }
  } catch {
    // Deliberate cancel (panel closed / incident swapped mid-stream): stay
    // silent — there is no UI left to report to. A genuine mid-stream drop
    // surfaces so the caller can reset its loading state.
    if (!signal?.aborted) {
      handlers.onError({
        code: "network_error",
        message: "The stream was interrupted — try again.",
      });
    }
    return;
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Body already disturbed (e.g. aborted) — nothing to release.
    }
  }
}


const KEY_LS = "codexray_api_key";
const PID_LS = "codexray_project_id";

export function getKey(): string {
  return typeof window === "undefined" ? "" : sessionStorage.getItem(KEY_LS) ?? "";
}

export function getPid(): string {
  return typeof window === "undefined" ? "" : sessionStorage.getItem(PID_LS) ?? "";
}

export function saveAuth(pid: string, key: string) {
  sessionStorage.setItem(PID_LS, pid);
  sessionStorage.setItem(KEY_LS, key);
}

export function clearAuth() {
  sessionStorage.removeItem(PID_LS);
  sessionStorage.removeItem(KEY_LS);
}

/** WebSocket endpoint. Auth travels in the Sec-WebSocket-Protocol header
 * (via streamProtocols) — never as a query parameter, so the key cannot
 * leak into access logs, proxies, or browser history. */
export function streamUrl(pid: string): string {
  return `${API_BASE.replace(/^http/, "ws")}/api/projects/${pid}/stream`;
}

/** Subprotocols offered on connect: a fixed token first, then the API key.
 * The server validates the cxr_ element and echoes only the fixed token. */
export function streamProtocols(key: string): string[] {
  return ["codexray.v1", key];
}

/** Public: true when the server gates project creation behind a license key. */
export async function licenseRequired(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/license`);
    if (!res.ok) return false;
    return ((await res.json()) as { required?: boolean }).required === true;
  } catch {
    return false; // API unreachable — demo/setup will surface the real error
  }
}
