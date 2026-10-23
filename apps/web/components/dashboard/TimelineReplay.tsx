"use client";

/* Synchronized timeline + incident replay player.
   Lanes come from spans; the cursor comes from replay actions.
   Reports the active service upward so the graph + inspector follow. */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReplayAction, Span } from "@/lib/api";

const SPEEDS = [0.5, 1, 2, 5, 10];

function actionAt(actions: ReplayAction[], t: number): ReplayAction | null {
  let cur: ReplayAction | null = null;
  for (const a of actions) {
    if (a.time <= t + 1e-9) cur = a;
    else break;
  }
  return cur;
}

export default function TimelineReplay({
  spans,
  actions,
  onActive,
}: {
  spans: Span[];
  actions: ReplayAction[] | null;
  onActive: (a: ReplayAction | null) => void;
}) {
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [cursor, setCursor] = useState(0);
  const onActiveRef = useRef(onActive);
  useEffect(() => {
    onActiveRef.current = onActive;
  });
  const lastActionRef = useRef<ReplayAction | null>(null);

  const { t0, total } = useMemo(() => {
    if (!spans.length) return { t0: 0, total: 1 };
    const starts = spans.map((s) => s.timestamp);
    const ends = spans.map((s) => s.timestamp + s.duration_ms / 1000);
    const a = Math.min(...starts);
    const b = Math.max(...ends);
    return { t0: a, total: Math.max(b - a, 0.05) };
  }, [spans]);
  const span = actions && actions.length ? Math.max(actions[actions.length - 1].time + 0.2, total) : total;

  function emit(a: ReplayAction | null) {
    if (a !== lastActionRef.current) {
      lastActionRef.current = a;
      onActiveRef.current(a);
    }
  }

  useEffect(() => {
    if (!playing || !actions) return;
    let last = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const dt = ((now - last) / 1000) * speed;
      last = now;
      const atEnd = { done: false };
      setCursor((c) => {
        const next = c + dt;
        if (next >= span) {
          atEnd.done = true;
          return span;
        }
        return next;
      });
      if (atEnd.done) {
        setPlaying(false);
        emit(actions[actions.length - 1] ?? null);
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, span, actions]);

  const current = actions ? actionAt(actions, cursor) : null;
  const failAt = actions?.find((a) => a.action === "ERROR")?.time;

  function play() {
    if (!actions) return;
    if (cursor >= span) {
      setCursor(0);
      emit(actionAt(actions, 0));
    }
    setPlaying(true);
  }

  function restart() {
    if (!actions) return;
    setCursor(0);
    emit(actionAt(actions, 0));
    setPlaying(true);
  }

  function jumpToFailure() {
    if (!actions || failAt === undefined) return;
    setCursor(failAt);
    emit(actionAt(actions, failAt));
    setPlaying(false);
  }

  return (
    <div className="tl">
      <div className="tl__scale" aria-hidden="true">
        <span>0.0s</span>
        <span>{(span / 2).toFixed(1)}s</span>
        <span>{span.toFixed(1)}s</span>
      </div>
      <div className="tl__lanes">
        {spans.length === 0 && <div className="empty">Timeline follows the selected trace.</div>}
        {spans.map((s) => {
          const left = ((s.timestamp - t0) / span) * 100;
          const width = Math.max(1.5, ((s.duration_ms / 1000) / span) * 100);
          return (
            <div key={s.span_id} className={`tl__lane${s.status === "error" ? " err" : ""}`} title={`${s.service} — ${s.operation}`}>
              <i style={{ left: `${Math.min(left, 100)}%`, width: `${Math.min(width, 100 - Math.min(left, 100))}%` }} />
            </div>
          );
        })}
        {actions && (
          <div className="tl__cursor" style={{ left: `${(cursor / span) * 100}%` }} aria-hidden="true" />
        )}
      </div>
      <div className="replay">
        {!actions ? (
          <span style={{ fontSize: 13, color: "#6b7484" }}>Select an incident to load its replay.</span>
        ) : (
          <>
            <button type="button" className="primary" onClick={() => (playing ? setPlaying(false) : play())}>
              {playing ? "⏸ Pause" : cursor > 0 ? "▶ Resume" : "▶ Play"}
            </button>
            <button type="button" onClick={restart}>↶ Restart</button>
            {failAt !== undefined && (
              <button type="button" onClick={jumpToFailure}>⏭ Jump to failure</button>
            )}
            <span className="replay__speed" role="group" aria-label="Playback speed">
              {SPEEDS.map((s) => (
                <button key={s} type="button" className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>
                  {s}x
                </button>
              ))}
            </span>
            <span className="replay__clock">{cursor.toFixed(1)}s / {span.toFixed(1)}s</span>
          </>
        )}
      </div>
      <div className="replay__now" aria-live="polite">
        {current && (
          <>
            <b>{current.action}</b> — {current.service}
            {current.message ? ` · ${current.message}` : ""}
          </>
        )}
      </div>
    </div>
  );
}
