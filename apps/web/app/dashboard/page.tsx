"use client";

/* CodeXRay control center: live graph + incidents + trace + inspector
   + synchronized timeline/replay. All data from the FastAPI backend. */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { LogoMark } from "@/components/SiteNav";
import ApiKeyGate from "@/components/dashboard/ApiKeyGate";
import AiDrawer from "@/components/dashboard/AiDrawer";
import DashGraph from "@/components/dashboard/DashGraph";
import Incidents from "@/components/dashboard/Incidents";
import Inspector from "@/components/dashboard/Inspector";
import LiveFeed, { type FeedEvent } from "@/components/dashboard/LiveFeed";
import LogPanel from "@/components/dashboard/LogPanel";
import TimelineReplay from "@/components/dashboard/TimelineReplay";
import TraceView from "@/components/dashboard/TraceView";
import {
  ApiError,
  clearAuth,
  endpoints,
  getKey,
  getPid,
  streamProtocols,
  streamUrl,
  type Graph,
  type ConnectionInfo,
  type Incident,
  type LogLine,
  type ReplayAction,
  type Trace,
  type TraceSummary,
} from "@/lib/api";

export default function DashboardPage() {
  // Session storage only exists in the browser: render a static skeleton
  // until hydration completes so server HTML always matches first paint.
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false
  );
  const [authed, setAuthed] = useState(() => !!getKey() && !!getPid());
  const [pid, setPid] = useState(() => getPid());
  // Deep-link prefill (?pid=): read once — only consumed post-hydration by
  // the gate, so server HTML never depends on it.
  const [prefill] = useState(() =>
    typeof window === "undefined"
      ? ""
      : (new URLSearchParams(window.location.search).get("pid") ?? "")
  );
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState("");
  const [wsLive, setWsLive] = useState(false);

  const [graph, setGraph] = useState<Graph | null>(null);
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [trace, setTrace] = useState<Trace | null>(null);

  const [selService, setSelService] = useState<string | null>(null);
  const [selIncident, setSelIncident] = useState<string | null>(null);
  const [selSpan, setSelSpan] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayAction[] | null>(null);
  const [activeReplay, setActiveReplay] = useState<ReplayAction | null>(null);
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [feedPaused, setFeedPaused] = useState(false);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [logsPaused, setLogsPaused] = useState(false);
  const [injecting, setInjecting] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  // BYOK connection lives at page level so switching incidents (which remounts
  // the drawer) doesn't force the user to reconnect. It is an opaque,
  // server-side id — never the provider key.
  const [aiConn, setAiConn] = useState<ConnectionInfo | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedId = useRef(0);
  const feedPausedRef = useRef(false);
  const logId = useRef(0);
  const logsPausedRef = useRef(false);

  // Trailing-debounce refetch: many frames per second collapse into one
  // graph + trace refresh (≤1 per 1.5s). Stable: refs + setters only.
  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) return;
    refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null;
      endpoints.graph(getPid()).then(setGraph).catch(() => {});
      endpoints.traces(getPid()).then(setTraces).catch(() => {});
    }, 1500);
  }, []);

  const pushFeed = useCallback((e: Omit<FeedEvent, "id" | "time">) => {
    const id = (feedId.current += 1);
    const time = new Date().toLocaleTimeString("en-GB", { hour12: false });
    setFeed((prev) => [...prev.slice(-49), { ...e, id, time }]);
  }, []);

  const pushLog = useCallback((l: Omit<LogLine, "id">) => {
    const id = (logId.current += 1);
    setLogs((prev) => [...prev.slice(-199), { ...l, id }]);
  }, []);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    Promise.all([
      endpoints.graph(getPid()),
      endpoints.traces(getPid()),
      endpoints.incidents(getPid()),
      endpoints.logs(getPid()).catch(() => [] as LogLine[]),
    ])
      .then(async ([g, t, i, lg]) => {
        if (cancelled) return;
        setGraph(g);
        setTraces(t);
        setIncidents(i);
        // GET returns newest-first; store oldest→newest for the panel.
        setLogs(
          [...lg].reverse().map((l) => ({ ...l, id: (logId.current += 1) }))
        );
        setApiError("");
        if (t.length) {
          const full = await endpoints.trace(t[0].trace_id);
          if (!cancelled) setTrace(full);
        }
        if (!cancelled) setLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setApiError(
          e instanceof ApiError ? `${e.status}: ${e.message}` : "API unreachable — is it on :3101?"
        );
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authed]);

  // Live stream: service statuses, new incidents.
  useEffect(() => {
    if (!authed || !pid) return;
    const key = getKey();
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;
    function connect() {
      ws = new WebSocket(streamUrl(pid), streamProtocols(key));
      wsRef.current = ws;
      ws.onopen = () => setWsLive(true);
      ws.onclose = () => {
        setWsLive(false);
        if (!closed) retry = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string);
          const live = !feedPausedRef.current;
          if (msg.type === "service_status") {
            if (live) pushFeed({ kind: "service_status", service: msg.service, detail: `→ ${msg.status}` });
            setGraph((g) =>
              g ? { ...g, nodes: g.nodes.map((n) => (n.id === msg.service ? { ...n, status: msg.status } : n)) } : g
            );
          } else if (msg.type === "incident") {
            if (live) pushFeed({ kind: "incident", service: msg.incident_id, detail: msg.title });
            endpoints.incidents(getPid()).then(setIncidents).catch(() => {});
            scheduleRefresh();
          } else if (msg.type === "error") {
            if (live) pushFeed({ kind: "error", service: msg.service, detail: msg.operation ?? "error" });
            setGraph((g) =>
              g ? { ...g, nodes: g.nodes.map((n) => (n.id === msg.service ? { ...n, status: "error" } : n)) } : g
            );
            scheduleRefresh();
          } else if (msg.type === "new_event") {
            if (live) pushFeed({ kind: "new_event", service: msg.service, detail: msg.operation ?? "" });
            scheduleRefresh();
          } else if (msg.type === "log") {
            if (!logsPausedRef.current) {
              pushLog({
                ts: typeof msg.ts === "number" ? msg.ts : Date.now() / 1000,
                level: msg.level ?? "info",
                service: msg.service ?? "",
                message: msg.message ?? "",
                source_file: msg.source_file ?? "",
                received_at: Date.now() / 1000,
              });
            }
          }
        } catch {
          /* ignore malformed frames */
        }
      };
    }
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      ws?.close();
      wsRef.current = null;
    };
  }, [authed, pid, pushFeed, pushLog, scheduleRefresh]);

  async function openTrace(tid: string) {
    try {
      const full = await endpoints.trace(tid);
      setTrace(full);
      setSelSpan(null);
      setActiveReplay(null);
      setSelIncident((cur) => {
        const inc = incidents.find((i) => i.trace_id === tid);
        if (inc && cur !== inc.incident_id) {
          endpoints.replay(inc.incident_id).then((r) => setReplay(r.actions)).catch(() => setReplay(null));
          return inc.incident_id;
        }
        return cur;
      });
    } catch (e) {
      setApiError(e instanceof ApiError ? `${e.status}: ${e.message}` : "trace load failed");
    }
  }

  async function openIncident(iid: string | null) {
    setSelIncident(iid);
    setReplay(null);
    setActiveReplay(null);
    if (!iid) return;
    const inc = incidents.find((i) => i.incident_id === iid);
    if (!inc) return;
    try {
      const [r, full] = await Promise.all([
        endpoints.replay(iid),
        endpoints.trace(inc.trace_id),
      ]);
      setReplay(r.actions);
      setTrace(full);
      setSelSpan(null);
    } catch (e) {
      setApiError(e instanceof ApiError ? `${e.status}: ${e.message}` : "incident load failed");
    }
  }

  function toggleFeedPaused() {
    feedPausedRef.current = !feedPausedRef.current;
    setFeedPaused(feedPausedRef.current);
  }

  function toggleLogsPaused() {
    logsPausedRef.current = !logsPausedRef.current;
    setLogsPaused(logsPausedRef.current);
  }

  async function injectFailure() {
    if (!pid || injecting) return;
    setInjecting(true);
    setApiError("");
    try {
      await endpoints.demoInject(pid);
      // The WS "incident" frame refetches the incident list automatically.
    } catch (e) {
      setApiError(
        e instanceof ApiError ? `${e.status}: ${e.message}` : "inject failed — is the API running?"
      );
    } finally {
      setInjecting(false);
    }
  }

  if (!mounted) {
    return (
      <div className="gate">
        <div className="gate__card">
          <p>Connecting to control center…</p>
        </div>
      </div>
    );
  }
  if (!authed) return <ApiKeyGate initialPid={prefill} onAuthed={() => { setPid(getPid()); setLoading(true); setAuthed(true); }} />;

  const selIncidentObj = incidents.find((i) => i.incident_id === selIncident) ?? null;
  const selSpanObj = trace?.spans.find((s) => s.span_id === selSpan) ?? null;
  // Replay cursor drives graph highlight + inspector follow.
  const highlightSvc = activeReplay?.service ?? selService;
  const inspectorSpan =
    selSpanObj ??
    (activeReplay ? trace?.spans.find((s) => s.service === activeReplay.service) ?? null : null);

  const sum = graph?.summary;

  return (
    <>
      <header className="dash-top">
        <Link href="/" className="dash-brand" aria-label="Back to site">
          <LogoMark size={20} />
          <span>codexray <small>CONTROL CENTER</small></span>
        </Link>
        <span className="dash-pid">{pid}</span>
        <span className={`live-pill${wsLive ? "" : " off"}`}>
          <span className="dot" aria-hidden="true" />
          {wsLive ? "LIVE" : "RECONNECTING"}
        </span>
        <span className="spacer" />
        <button
          type="button"
          className="dash-link dash-inject"
          onClick={() => void injectFailure()}
          disabled={injecting || loading}
        >
          {injecting ? "Injecting…" : "⚡ Inject failure"}
        </button>
        <button
          type="button"
          className="dash-link"
          onClick={() => { clearAuth(); setAuthed(false); wsRef.current?.close(); }}
        >
          Disconnect
        </button>
      </header>

      {apiError && <div className="dash-banner err" role="alert">{apiError}</div>}
      {!wsLive && !apiError && !loading && (
        <div className="dash-banner" role="status">Live stream reconnecting — graph shows last snapshot.</div>
      )}

      <main className="dash-grid">
        <section className="panel span-12" aria-label="System health">
          <div className="health">
            {[
              { v: String(sum?.services ?? "—"), l: "services", c: "" },
              { v: String(sum?.healthy ?? "—"), l: "healthy", c: "ok" },
              { v: String(sum?.degraded ?? "—"), l: "degraded", c: "warn" },
              { v: String(sum?.failing ?? "—"), l: "failing", c: (sum?.failing ?? 0) > 0 ? "bad" : "" },
              { v: sum ? sum.requests_per_min.toFixed(0) : "—", l: "req/min", c: "" },
              { v: sum ? `${(sum.error_rate * 100).toFixed(1)}%` : "—", l: "error rate", c: (sum?.error_rate ?? 0) > 0.02 ? "bad" : "" },
            ].map((s) => (
              <div key={s.l} className={`health__stat ${s.c}`}>
                <b>{loading ? "…" : s.v}</b>
                <span>{s.l}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="panel span-8" aria-label="Live system graph">
          <div className="panel__head">
            <span className="panel__eyebrow">[live]</span>
            <h2 className="panel__title">System graph</h2>
            <span className="right">{graph ? `${graph.nodes.length} services · ${graph.edges.length} edges` : ""}</span>
          </div>
          {loading && !graph ? (
            <div className="empty">Loading graph…</div>
          ) : (
            <DashGraph
              nodes={graph?.nodes ?? []}
              edges={graph?.edges ?? []}
              selected={highlightSvc}
              onSelect={setSelService}
            />
          )}
        </section>

        <div className="rail">
          <section className="panel" aria-label="Incidents">
            <div className="panel__head">
              <span className="panel__eyebrow">[incidents]</span>
              <h2 className="panel__title">Incidents</h2>
              <span className="right">
                {incidents.length} open{" "}
                {selIncident && (
                  <button type="button" className="dash-link" onClick={() => setAiOpen(true)}>
                    AI Summary
                  </button>
                )}
              </span>
            </div>
            <Incidents items={incidents} selected={selIncident} onSelect={openIncident} />
          </section>
          <section className="panel" aria-label="Live events">
            <div className="panel__head">
              <span className="panel__eyebrow">[live]</span>
              <h2 className="panel__title">Event feed</h2>
              <span className="right">
                <button type="button" className="dash-link" onClick={toggleFeedPaused}>
                  {feedPaused ? "Resume" : "Pause"}
                </button>
              </span>
            </div>
            <LiveFeed items={feed} />
          </section>
        </div>

        <section className="panel span-8" aria-label="Request trace">
          <div className="panel__head">
            <span className="panel__eyebrow">[trace]</span>
            <h2 className="panel__title">Request trace</h2>
          </div>
          <TraceView
            trace={trace}
            summaries={traces}
            selectedSpan={selSpan}
            onSelectTrace={openTrace}
            onSelectSpan={setSelSpan}
          />
        </section>

        <section className="panel span-4" aria-label="Event inspector">
          <div className="panel__head">
            <span className="panel__eyebrow">[inspect]</span>
            <h2 className="panel__title">Inspector</h2>
          </div>
          <Inspector span={inspectorSpan} incident={selIncidentObj} />
        </section>

        <section className="panel span-12" aria-label="Timeline and replay">
          <div className="panel__head">
            <span className="panel__eyebrow">[replay]</span>
            <h2 className="panel__title">Timeline</h2>
            <span className="right">{trace ? trace.trace_id : "no trace selected"}</span>
          </div>
          <TimelineReplay
            key={selIncident ?? trace?.trace_id ?? "none"}
            spans={trace?.spans ?? []}
            actions={replay}
            onActive={setActiveReplay}
          />
        </section>

        <section className="panel span-12" aria-label="Live logs">
          <div className="panel__head">
            <span className="panel__eyebrow">[logs]</span>
            <h2 className="panel__title">Logs</h2>
            <span className="right">{logs.length} lines · codexray logs</span>
          </div>
          <LogPanel
            items={logs}
            paused={logsPaused}
            onTogglePause={toggleLogsPaused}
          />
        </section>
      </main>
      <AiDrawer
        key={selIncident ?? trace?.trace_id ?? "none"}
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        pid={getPid()}
        incident={selIncidentObj}
        trace={trace}
        conn={aiConn}
        onConnChange={setAiConn}
      />
    </>
  );
}
