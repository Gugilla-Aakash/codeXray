/* CodeXRay browser SDK — zero dependencies, fail-silent.
 *
 * One trace from click to database:
 *   init({ apiUrl, apiKey, service }) once, then every wrapped fetch
 *   carries X-CodeXRay-Trace / X-CodeXRay-Parent headers that the
 *   Python middleware continues. Elements with `data-cx-action` emit
 *   click spans automatically.
 */

const TRACE_HEADER = "X-CodeXRay-Trace";
const PARENT_HEADER = "X-CodeXRay-Parent";
const AMBIENT_TTL_MS = 60_000;

function rid(n) {
  try {
    const bytes = new Uint8Array(n);
    crypto.getRandomValues(bytes);
    return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, n);
  } catch {
    return Math.random().toString(16).slice(2, 2 + n).padEnd(n, "0");
  }
}

const state = {
  apiUrl: "",
  apiKey: "",
  service: "browser",
  traceId: null,
  traceStartedAt: 0,
  fetchWrapped: false,
  clickBound: false,
};

function send(events) {
  if (!state.apiUrl || !state.apiKey) return;
  try {
    // Plain fetch only: sendBeacon cannot carry the X-API-Key header
    // (keyless posts are rejected), and keepalive fetches trip Chromium's
    // wildcard-origin CORS rejection. Plain async POST just works.
    fetch(`${state.apiUrl.replace(/\/$/, "")}/api/telemetry`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": state.apiKey },
      body: JSON.stringify({ events }),
    }).catch(() => {});
  } catch {
    /* telemetry must never break the page */
  }
}

function emit(span) {
  send([
    {
      trace_id: span.traceId,
      span_id: span.spanId,
      parent_span_id: span.parentSpanId ?? null,
      service: span.service,
      operation: span.operation,
      timestamp: span.startedAt / 1000,
      duration_ms: Math.round((Date.now() - span.startedAt) * 10) / 10,
      status: span.status,
      error: span.error ?? null,
      metadata: span.metadata ?? {},
    },
  ]);
}

function ensureTrace() {
  const now = Date.now();
  if (!state.traceId || now - state.traceStartedAt > AMBIENT_TTL_MS) {
    state.traceId = rid(16);
    state.traceStartedAt = now;
  }
  return state.traceId;
}

function wrapFetch() {
  if (state.fetchWrapped || typeof window === "undefined" || typeof window.fetch !== "function") return;
  state.fetchWrapped = true;
  const orig = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    let span = null;
    try {
      const rawUrl =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input?.url ?? "";
      if (state.apiUrl && String(rawUrl).startsWith(state.apiUrl.replace(/\/$/, ""))) {
        return orig(input, init);
      }
      const traceId = ensureTrace();
      const rawMethod =
        (init && init.method) ||
        (typeof input !== "string" && input?.method) ||
        "GET";
      const method = String(rawMethod).toUpperCase();
      span = {
        traceId,
        spanId: rid(16),
        parentSpanId: null,
        service: state.service,
        operation: `${method} ${String(rawUrl).split("?")[0].slice(-120)}`,
        startedAt: Date.now(),
        status: "success",
        metadata: {},
      };
      const prevHeaders =
        (init && init.headers) ||
        (typeof input !== "string" && input?.headers) ||
        undefined;
      const headers = new Headers(prevHeaders);
      headers.set(TRACE_HEADER, traceId);
      headers.set(PARENT_HEADER, span.spanId);
      const res = await orig(input, { ...init, headers });
      span.status = res.status >= 500 ? "error" : "success";
      span.metadata.status_code = res.status;
      return res;
    } catch (err) {
      if (span) {
        span.status = "error";
        span.error = { type: "FetchError", message: String((err && err.message) || err).slice(0, 200) };
      }
      throw err;
    } finally {
      if (span) emit(span);
    }
  };
}

function bindClicks() {
  if (state.clickBound || typeof document === "undefined" || typeof document.addEventListener !== "function") return;
  state.clickBound = true;
  document.addEventListener("click", (e) => {
    try {
      const el = e.target instanceof Element ? e.target.closest("[data-cx-action]") : null;
      if (!el) return;
      traceAction(el.getAttribute("data-cx-action") || "click", {
        text: (el.textContent || "").trim().slice(0, 80),
      });
    } catch {
      /* ignore */
    }
  });
}

export function init({ apiUrl, apiKey, service = "browser" } = {}) {
  state.apiUrl = apiUrl ?? "";
  state.apiKey = apiKey ?? "";
  state.service = service;
  wrapFetch();
  bindClicks();
  pageview();
}

export function pageview(path) {
  try {
    const traceId = rid(16);
    state.traceId = traceId;
    state.traceStartedAt = Date.now();
    emit({
      traceId,
      spanId: rid(16),
      parentSpanId: null,
      service: state.service,
      operation: `page view ${path ?? (typeof location !== "undefined" ? location.pathname : "/")}`,
      startedAt: Date.now(),
      status: "success",
      metadata: {},
    });
    return traceId;
  } catch {
    return null;
  }
}

export function traceAction(name, metadata) {
  try {
    const traceId = ensureTrace();
    emit({
      traceId,
      spanId: rid(16),
      parentSpanId: null,
      service: state.service,
      operation: `click: ${name}`,
      startedAt: Date.now(),
      status: "success",
      metadata: metadata ?? {},
    });
    return traceId;
  } catch {
    return null;
  }
}

export function currentTrace() {
  return state.traceId;
}

/* Test seam: reset module state between tests. Not part of the public API. */
export function __reset() {
  state.apiUrl = "";
  state.apiKey = "";
  state.service = "browser";
  state.traceId = null;
  state.traceStartedAt = 0;
  state.fetchWrapped = false;
  state.clickBound = false;
}
