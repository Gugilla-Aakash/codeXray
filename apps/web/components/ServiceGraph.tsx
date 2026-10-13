"use client";

/* Structured checkout-pipeline graph: labeled nodes, directed animated
   edges, and a looping live -> slow -> incident failure simulation.
   Reference language: Grafana Tempo service graph + React Flow edges. */

import { useEffect, useRef, useState } from "react";
import {
  Background,
  BaseEdge,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  getBezierPath,
  useEdgesState,
  useNodesState,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

type Status = "ok" | "slow" | "warn" | "error";

type SvcData = {
  label: string;
  kind: string;
  metric: string;
  status: Status;
};

type PulseData = {
  color: string;
  dur: string;
  dim?: boolean;
};

const STATUS_DOT: Record<Status, string> = {
  ok: "#30d158",
  slow: "#ff9f0a",
  warn: "#ff9f0a",
  error: "#ff3b30",
};

function ServiceNode({ data }: NodeProps<Node<SvcData>>) {
  const d = data as SvcData;
  const ghost = { opacity: 0, width: 1, height: 1, minWidth: 1, minHeight: 1 };
  return (
    <div className={`svc svc--${d.status}`}>
      <Handle type="target" position={Position.Left} id="l" isConnectable={false} style={ghost} />
      <Handle type="source" position={Position.Right} id="r" isConnectable={false} style={ghost} />
      <Handle type="source" position={Position.Top} id="t" isConnectable={false} style={ghost} />
      <Handle type="target" position={Position.Bottom} id="b" isConnectable={false} style={ghost} />
      <span className="svc__dot" style={{ background: STATUS_DOT[d.status] }} />
      <span className="svc__body">
        <span className="svc__label">{d.label}</span>
        <span className="svc__meta">
          [{d.kind}] {d.metric}
        </span>
      </span>
    </div>
  );
}

function PulseEdge(props: EdgeProps<Edge<PulseData>>) {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    data,
    label,
    markerEnd,
    style,
  } = props;
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        labelX={labelX}
        labelY={labelY}
        label={label}
        markerEnd={markerEnd}
        style={style}
      />
      {data && !data.dim && (
        <circle r={4.5} fill={data.color}>
          <animateMotion dur={data.dur} repeatCount="indefinite" path={path} />
        </circle>
      )}
    </>
  );
}

const nodeTypes = { svc: ServiceNode };
const edgeTypes = { pulse: PulseEdge };

type Phase = "live" | "slow" | "incident";

const PHASE_HUD: Record<Phase, string> = {
  live: "live — 1,240 req/min · p95 210ms · error 0.4%",
  slow: "postgres latency spike — p95 2.8s · retries climbing",
  incident: "INC-1024 checkout failure — root cause: postgres query timeout",
};

const BASE_NODES: Node<SvcData>[] = [
  { id: "browser", type: "svc", position: { x: 0, y: 195 }, data: { label: "browser", kind: "client", metric: "click pay", status: "ok" } },
  { id: "gateway", type: "svc", position: { x: 215, y: 195 }, data: { label: "api gateway", kind: "api", metric: "POST /checkout", status: "ok" } },
  { id: "auth", type: "svc", position: { x: 430, y: 40 }, data: { label: "auth", kind: "svc", metric: "jwt · 12ms", status: "ok" } },
  { id: "order", type: "svc", position: { x: 430, y: 310 }, data: { label: "order service", kind: "svc", metric: "create order", status: "ok" } },
  { id: "redis", type: "svc", position: { x: 680, y: 40 }, data: { label: "redis", kind: "cache", metric: "GET session · 4ms", status: "ok" } },
  { id: "postgres", type: "svc", position: { x: 680, y: 310 }, data: { label: "postgres", kind: "db", metric: "SELECT orders · 38ms", status: "ok" } },
  { id: "payment", type: "svc", position: { x: 920, y: 310 }, data: { label: "payment", kind: "svc", metric: "charge · 410ms", status: "ok" } },
  { id: "stripe", type: "svc", position: { x: 920, y: 40 }, data: { label: "stripe", kind: "ext", metric: "POST /charges", status: "ok" } },
];

const BASE_EDGES: Edge<PulseData>[] = [
  { id: "e1", source: "browser", sourceHandle: "r", target: "gateway", targetHandle: "l", type: "pulse", animated: false, label: "GET / · 200", data: { color: "#201d1d", dur: "1.8s" } },
  { id: "e2", source: "gateway", sourceHandle: "t", target: "auth", targetHandle: "b", type: "pulse", label: "verify · 12ms", data: { color: "#201d1d", dur: "2.2s" } },
  { id: "e3", source: "gateway", sourceHandle: "r", target: "order", targetHandle: "l", type: "pulse", label: "POST /checkout", data: { color: "#201d1d", dur: "1.6s" } },
  { id: "e4", source: "order", sourceHandle: "r", target: "postgres", targetHandle: "l", type: "pulse", label: "SELECT · 38ms", data: { color: "#201d1d", dur: "2s" } },
  { id: "e5", source: "order", sourceHandle: "t", target: "redis", targetHandle: "b", type: "pulse", label: "GET · 4ms", data: { color: "#201d1d", dur: "2.6s" } },
  { id: "e6", source: "order", sourceHandle: "r", target: "payment", targetHandle: "l", type: "pulse", label: "charge · 410ms", data: { color: "#201d1d", dur: "2.4s" } },
  { id: "e7", source: "payment", sourceHandle: "t", target: "stripe", targetHandle: "b", type: "pulse", label: "ext · 180ms", data: { color: "#201d1d", dur: "3s" } },
];

function overlay(phase: Phase): { nodes: Node<SvcData>[]; edges: Edge<PulseData>[] } {
  const nodes = BASE_NODES.map((n) => ({ ...n, data: { ...n.data } }));
  const edges = BASE_EDGES.map((e) => ({ ...e, data: { ...(e.data as PulseData) } }));
  const setNode = (id: string, patch: Partial<SvcData>) => {
    const n = nodes.find((x) => x.id === id);
    if (n) n.data = { ...n.data, ...patch };
  };
  const setEdge = (id: string, patch: Partial<PulseData>) => {
    const e = edges.find((x) => x.id === id);
    if (e) e.data = { ...(e.data as PulseData), ...patch };
  };

  if (phase === "slow") {
    setNode("postgres", { status: "slow", metric: "SELECT · 2840ms…" });
    setNode("order", { status: "slow", metric: "waiting on db" });
    setEdge("e4", { color: "#ff9f0a", dur: "4s" });
  }
  if (phase === "incident") {
    setNode("postgres", { status: "error", metric: "timeout 2840ms" });
    setNode("order", { status: "warn", metric: "order failed" });
    setNode("payment", { status: "warn", metric: "retrying…" });
    setNode("gateway", { status: "warn", metric: "504 upstream" });
    setNode("browser", { status: "error", metric: "checkout failed" });
    setEdge("e4", { color: "#ff3b30", dur: "1.2s" });
    setEdge("e3", { color: "#ff3b30", dur: "1.2s" });
    setEdge("e1", { color: "#ff3b30", dur: "1.2s" });
    setEdge("e6", { color: "#ff9f0a", dur: "1.4s" });
    setEdge("e2", { dim: true });
    setEdge("e5", { dim: true });
    setEdge("e7", { dim: true });
  }
  return { nodes, edges };
}

const PHASE_ORDER: Phase[] = ["live", "slow", "incident"];
const PHASE_MS: Record<Phase, number> = { live: 4200, slow: 2600, incident: 3800 };

export default function ServiceGraph() {
  const [nodes, setNodes] = useNodesState(BASE_NODES);
  const [edges, setEdges] = useEdgesState(BASE_EDGES);
  const [phase, setPhase] = useState<Phase>("live");
  const [paused, setPaused] = useState(false);
  const [frozen] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (frozen || paused) return;
    const t = setTimeout(() => {
      setPhase((p) => {
        const next = PHASE_ORDER[(PHASE_ORDER.indexOf(p) + 1) % PHASE_ORDER.length];
        const o = overlay(next);
        setNodes(o.nodes);
        setEdges(o.edges);
        return next;
      });
    }, PHASE_MS[phase]);
    return () => clearTimeout(t);
  }, [phase, paused, frozen, setNodes, setEdges]);

  const togglePause = () => {
    const svg = wrapRef.current?.querySelector("svg");
    if (!paused) svg?.pauseAnimations();
    else svg?.unpauseAnimations();
    setPaused((p) => !p);
  };

  return (
    <>
      <div className="graph-wrap" ref={wrapRef} aria-hidden="true">
        <ReactFlow
          nodes={nodes}
          edges={edges.map((e) => ({
            ...e,
            markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#646262" },
            style: { stroke: "#646262", strokeWidth: 1.5 },
          }))}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.08 }}
          minZoom={0.5}
          maxZoom={1.5}
          panOnDrag={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: false }}
        >
          <Background gap={28} size={1.5} color="rgba(15,0,0,0.08)" />
        </ReactFlow>
      </div>
      <p className="visually-hidden">
        Live checkout pipeline: browser to gateway to auth and order service,
        order to postgres and payment. Postgres times out; the failure
        propagates back to checkout.
      </p>
      <div className="hero-visual__hud">
        <span data-phase={phase}>{PHASE_HUD[phase]}</span>
        {!frozen && (
          <button type="button" onClick={togglePause}>
            {paused ? "resume motion" : "pause motion"}
          </button>
        )}
      </div>
    </>
  );
}
