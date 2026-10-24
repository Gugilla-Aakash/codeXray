"use client";

/* BYOK investigation chat — streaming, grounded in one incident.
   Uses the SSE-over-POST stream endpoint. History is held client-side and
   capped server-side; the provider key lives only in the backend. */

import { useEffect, useRef, useState } from "react";
import {
  endpoints,
  streamInvestigate,
  type ChatTurn,
  type ConnectionInfo,
  type Incident,
} from "@/lib/api";
import { renderLite } from "./AiDrawer";

const SUGGESTIONS = [
  "Why did this request fail?",
  "Which service caused the failure?",
  "Could this be connection pool exhaustion?",
  "How would you fix this?",
  "Explain this error like I'm a junior developer.",
];

export default function InvestigateChat({
  onClose,
  onDisconnect,
  pid,
  incident,
  connection,
}: {
  onClose: () => void;
  onDisconnect: () => void;
  pid: string;
  incident: Incident | null;
  connection: ConnectionInfo | null;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [meta, setMeta] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const incidentId = incident?.incident_id ?? null;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, streaming]);

  // Abort any in-flight stream when the panel unmounts (close / incident swap).
  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function send() {
    const q = draft.trim();
    if (!q || streaming || !connection || !incidentId) return;
    setError("");
    setMeta("");
    const history = turns;
    setTurns([...history, { role: "user", content: q }, { role: "assistant", content: "" }]);
    setDraft("");
    setStreaming(true);

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let acc = "";

    try {
      await streamInvestigate(
        pid,
        { connectionId: connection.connectionId, incidentId, message: q, history },
        {
          onDelta: (t) => {
            acc += t;
            setTurns((prev) => {
              const copy = prev.slice();
              copy[copy.length - 1] = { role: "assistant", content: acc };
              return copy;
            });
          },
          onDone: (info) => {
            const bits: string[] = [];
            if (info.model) bits.push(info.model);
            if (typeof info.ttftMs === "number") bits.push(`ttft ${info.ttftMs}ms`);
            if (typeof info.durationMs === "number") bits.push(`${info.durationMs}ms`);
            setMeta(bits.join(" · "));
            setStreaming(false);
          },
          onError: (e) => {
            setError(e.message);
            setTurns((prev) => (prev[prev.length - 1]?.content === "" ? prev.slice(0, -1) : prev));
            setStreaming(false);
          },
        },
        ctrl.signal
      );
    } catch (e) {
      // streamInvestigate reports expected failures via onError; this only
      // guards against a rejection escaping (e.g. a late abort racing the
      // reader) so it can never surface as an unhandled rejection, and the
      // spinner can never get stuck on.
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError("Investigation failed — try again.");
      setTurns((prev) => (prev[prev.length - 1]?.content === "" ? prev.slice(0, -1) : prev));
      setStreaming(false);
    }
  }

  async function disconnect() {
    if (!connection) return;
    try {
      await endpoints.aiDisconnect(pid, connection.connectionId);
    } catch {
      // best-effort; the server drops it on TTL anyway
    }
    onDisconnect();
  }

  if (!connection) return null;

  return (
    <div className="inv-modal" role="dialog" aria-modal="true" aria-label="AI investigation chat">
      <div className="inv-modal__scrim" onClick={onClose} aria-hidden="true" />
      <div className="inv-card inv-card--wide">
        <div className="inv-card__head">
          <div>
            <span className="panel__eyebrow">[investigate]</span>
            <h2 className="panel__title">AI investigation</h2>
            <div className="ai-ctx">
              {connection.provider} · {connection.model} · {incidentId ?? "no incident"}
            </div>
          </div>
          <span className="inv-head-actions">
            {turns.length > 0 && (
              <button type="button" className="dash-link" onClick={() => setTurns([])}>
                Clear
              </button>
            )}
            <button type="button" className="dash-link" onClick={disconnect}>
              Disconnect
            </button>
            <button type="button" className="dash-link" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </span>
        </div>

        <div className="inv-chat" aria-live="polite">
          {!incidentId && (
            <div className="empty">Select an incident first to ground the investigation.</div>
          )}
          {incidentId && turns.length === 0 && (
            <div className="inv-suggest">
              <div className="empty">Ask about this incident — answers cite this trace only.</div>
              <div className="inv-chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="inv-chip" onClick={() => setDraft(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((m, i) => (
            <div key={i} className={`inv-msg inv-msg--${m.role}`}>
              {m.content ? renderLite(m.content) : <span className="inv-caret" aria-label="streaming…" />}
            </div>
          ))}
          <div ref={endRef} />
        </div>

        {error && (
          <div className="ai-err" role="alert">
            {error}
          </div>
        )}
        {meta && <div className="ai-meta"><span>{meta}</span></div>}

        <div className="inv-input replay">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={incidentId ? "Ask about this incident…" : "Select an incident first"}
            aria-label="Ask the investigation assistant"
            maxLength={2000}
            disabled={!incidentId || streaming}
          />
          <button
            type="button"
            className="primary"
            onClick={() => void send()}
            disabled={streaming || !draft.trim() || !incidentId}
          >
            Send
          </button>
        </div>
        <p className="inv-hint inv-hint--foot">
          Runs on your provider key · CodeXRay never stores it.
        </p>
      </div>
    </div>
  );
}
