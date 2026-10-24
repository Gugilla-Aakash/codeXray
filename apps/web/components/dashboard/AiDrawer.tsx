"use client";

/* CodeXRay AI drawer: incident summary (Groq, CodeXRay's own budget).
   Generic for any project/trace — driven purely by props, never hardcoded
   to the demo seed. Read-only consumer of dashboard state.
   Deeper conversation is BYOK — see InvestigateDialog / InvestigateChat. */

import { useEffect, useRef, useState } from "react";
import { ApiError, endpoints, type ConnectionInfo, type Incident, type Trace } from "@/lib/api";
import InvestigateChat from "./InvestigateChat";
import InvestigateDialog from "./InvestigateDialog";

export function renderLite(text: string): React.ReactNode[] {
  // Minimal safe markdown-lite: **bold**, `code`, line breaks. No HTML injection.
  return text.split("\n").map((line, i) => {
    const parts: React.ReactNode[] = [];
    const re = /(\*\*.+?\*\*|`[^`]+`)/g;
    let last = 0;
    let m: RegExpExecArray | null;
    let k = 0;
    while ((m = re.exec(line)) !== null) {
      if (m.index > last) parts.push(line.slice(last, m.index));
      const tok = m[0];
      if (tok.startsWith("**")) parts.push(<b key={k++}>{tok.slice(2, -2)}</b>);
      else parts.push(<code key={k++} className="ai-code">{tok.slice(1, -1)}</code>);
      last = m.index + tok.length;
    }
    if (last < line.length) parts.push(line.slice(last));
    const bullet = /^\s*[-*]\s+/.test(line);
    return (
      <p key={i} className={bullet ? "ai-bullet" : undefined}>
        {parts.length ? parts : "\u00a0"}
      </p>
    );
  });
}

export default function AiDrawer({
  open,
  onClose,
  pid,
  incident,
  trace,
  conn,
  onConnChange,
}: {
  open: boolean;
  onClose: () => void;
  pid: string;
  incident: Incident | null;
  trace: Trace | null;
  conn: ConnectionInfo | null;
  onConnChange: (conn: ConnectionInfo | null) => void;
}) {
  const [summary, setSummary] = useState<string | null>(null);
  const [sumMeta, setSumMeta] = useState<string>("");
  // Starts true: fresh mount (parent remounts per incident via key) shows the
  // loading state immediately with no synchronous setState needed in effects.
  const [sumLoading, setSumLoading] = useState(true);
  const [sumError, setSumError] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [showConnect, setShowConnect] = useState(false);
  const reqId = useRef(0);

  const incidentId = incident?.incident_id ?? null;
  const traceId = incident?.trace_id ?? trace?.trace_id ?? null;

  function sumErrMsg(e: unknown): string {
    return e instanceof ApiError
      ? e.status === 503
        ? "Server AI not configured — add GROQ_API_KEY to services/api/.env and restart :3101."
        : `${e.status}: ${e.message}`
      : "AI unreachable — is the API on :3101?";
  }

  // Button-driven reload (event handler: synchronous setState is fine here).
  function loadSummary() {
    if (!incidentId) return;
    const id = ++reqId.current;
    setSumLoading(true);
    setSumError("");
    endpoints
      .aiSummary(incidentId)
      .then((res) => {
        if (reqId.current !== id) return;
        setSummary(res.summary);
        setSumMeta(`${res.cached ? "cached" : "fresh"} · ${res.model}`);
        setSumLoading(false);
      })
      .catch((e: unknown) => {
        if (reqId.current !== id) return;
        setSummary(null);
        setSumMeta("");
        setSumError(sumErrMsg(e));
        setSumLoading(false);
      });
  }

  // Auto-load on open / incident change. Mirrors the dashboard page's
  // fetch-in-effect pattern: state only settles inside promise callbacks,
  // never synchronously in the effect body.
  useEffect(() => {
    if (!open || !incidentId) return;
    const id = ++reqId.current;
    endpoints
      .aiSummary(incidentId)
      .then((res) => {
        if (reqId.current !== id) return;
        setSummary(res.summary);
        setSumMeta(`${res.cached ? "cached" : "fresh"} · ${res.model}`);
        setSumError("");
        setSumLoading(false);
      })
      .catch((e: unknown) => {
        if (reqId.current !== id) return;
        setSummary(null);
        setSumMeta("");
        setSumError(sumErrMsg(e));
        setSumLoading(false);
      });
  }, [open, incidentId]);

  // Escape closes the drawer; parent keeps all selection state intact.
  // While a BYOK overlay is open, let that overlay own Escape instead.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !showConnect && !chatOpen) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, showConnect, chatOpen]);

  if (!open) return null;

  return (
    <>
      <div className="ai-scrim" onClick={onClose} aria-hidden="true" />
      <aside className="ai-drawer" role="dialog" aria-label="AI incident summary">
        <div className="ai-head">
          <div>
            <span className="panel__eyebrow">[ai]</span>
            <h2 className="panel__title">Incident AI</h2>
            <div className="ai-ctx">
              {incidentId ?? "no incident"} · {traceId ?? "no trace"}
            </div>
          </div>
          <button type="button" className="dash-link" onClick={onClose} aria-label="Close AI drawer">
            ✕
          </button>
        </div>

        <div className="ai-body">
          <section aria-label="AI summary">
            <h3 className="ai-sec">Summary</h3>
            {!incidentId ? (
              <div className="empty">Select an incident to generate a summary.</div>
            ) : sumLoading && !summary ? (
              <div className="empty">Asking Groq… grounding in trace {traceId}…</div>
            ) : sumError ? (
              <div className="ai-err" role="alert">
                {sumError}
                <div>
                  <button type="button" className="dash-link" onClick={loadSummary}>
                    Retry
                  </button>
                </div>
              </div>
            ) : summary ? (
              <>
                <div className="ai-summary">{renderLite(summary)}</div>
                <div className="ai-meta">
                  <span>{sumMeta}</span>
                  <span>
                    <button
                      type="button"
                      className="dash-link"
                      onClick={() => navigator.clipboard?.writeText(summary).catch(() => {})}
                    >
                      Copy
                    </button>
                  </span>
                </div>
              </>
            ) : null}
          </section>

          <section aria-label="AI investigation">
            <h3 className="ai-sec">Investigation</h3>
            <p className="inv-hint">
              Ask follow-ups grounded in this trace. Deep investigation runs on{" "}
              <b>your own provider key</b> — you pay your provider, not CodeXRay.
            </p>
            <div className="replay ai-inv-row">
              <button
                type="button"
                className="primary"
                disabled={!incidentId}
                onClick={() => (conn ? setChatOpen(true) : setShowConnect(true))}
              >
                {conn ? "Continue investigation 🔍" : "Investigate with AI 🔍"}
              </button>
            </div>
            {conn && (
              <div className="ai-meta">
                <span>
                  {conn.provider} · {conn.model}
                </span>
                <span>
                  <button
                    type="button"
                    className="dash-link"
                    onClick={async () => {
                      setChatOpen(false);
                      if (conn) {
                        try {
                          await endpoints.aiDisconnect(pid, conn.connectionId);
                        } catch {
                          // best-effort; server drops it on TTL anyway
                        }
                      }
                      onConnChange(null);
                    }}
                  >
                    Change
                  </button>
                </span>
              </div>
            )}
          </section>
        </div>
      </aside>

      {showConnect && (
        <InvestigateDialog
          pid={pid}
          onClose={() => setShowConnect(false)}
          onConnected={(c) => {
            onConnChange(c);
            setShowConnect(false);
            setChatOpen(true);
          }}
        />
      )}
      {chatOpen && (
        <InvestigateChat
          key={incidentId ?? "none"}
          onClose={() => setChatOpen(false)}
          onDisconnect={() => {
            setChatOpen(false);
            onConnChange(null);
          }}
          pid={pid}
          incident={incident}
          connection={conn}
        />
      )}
    </>
  );
}
