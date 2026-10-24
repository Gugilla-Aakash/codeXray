"use client";

/* Live system graph: backend nodes/edges laid out in columns,
   traveling request pulses, click-to-inspect. Dark ops styling. */

import { useMemo } from "react";
import {
  Background,
  BaseEdge,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  getBezierPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphEdge, GraphNode } from "@/lib/api";

type PulseData = { color: string; dur: string; dim?: boolean };

const DOT: Record<string, string> = {
  healthy: "#30d158",
  ok: "#30d158",
  degraded: "#ff9f0a",
  slow: "#ff9f0a",
  warn: "#ff9f0a",
  warning: "#ff9f0a",
  error: "#ff3b30",
  critical: "#ff3b30",
};

function DNode({ data, selected }: NodeProps<Node<{ label: string; meta: string; status: string }>>) {
  const d = data as { label: string; meta: string; status: string };
  const st = (d.status || "healthy").toLowerCase();
  const ghost = { opacity: 0, width: 1, height: 1, minWidth: 1, minHeight: 1 };
  return (
    <div className={`dnode dnode--${st}${selected ? " sel" : ""}`}>
      <Handle type="target" position={Position.Left} id="l" isConnectable={false} style={ghost} />
      <Handle type="source" position={Position.Right} id="r" isConnectable={false} style={ghost} />
      <Handle type="source" position={Position.Top} id="t" isConnectable={false} style={ghost} />
      <Handle type="target" position={Position.Bottom} id="b" isConnectable={false} style={ghost} />
      <span className="dnode__dot" style={{ background: DOT[st] ?? "#9aa3b2" }} />
      <span>
        <span className="dnode__label">{d.label}</span>
        <span className="dnode__meta">{d.meta}</span>
      </span>
    </div>
  );
}

function PulseEdge(props: EdgeProps<Edge<PulseData>>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, label, markerEnd, style } = props;
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        labelX={labelX}
        labelY={labelY}
        label={label}
        labelStyle={{ fill: "#9aa3b2", fontSize: 10 }}
        labelBgStyle={{ fill: "#141821" }}
        labelBgPadding={[4, 3]}
        labelBgBorderRadius={3}
        markerEnd={markerEnd}
        style={style}
      />
      {data && !data.dim && (
        <circle r={4} fill={data.color}>
          <animateMotion dur={data.dur} repeatCount="indefinite" path={path} />
        </circle>
      )}
    </>
  );
}

const nodeTypes = { dnode: DNode };
const edgeTypes = { pulse: PulseEdge };

function layout(nodes: GraphNode[], edges: GraphEdge[]): Node[] {
  const incoming: Record<string, number> = {};
  const out: Record<string, string[]> = {};
  for (const n of nodes) incoming[n.id] = 0;
  for (const e of edges) {
    if (e.source === e.target) continue;
    if (!(e.source in incoming) || !(e.target in incoming)) continue;
    incoming[e.target] += 1;
    (out[e.source] ||= []).push(e.target);
  }
  const depth: Record<string, number> = {};
  const queue = nodes.filter((n) => incoming[n.id] === 0).map((n) => n.id);
  for (const id of queue) depth[id] = 0;
  const seen = new Set(queue);
  while (queue.length) {
    const id = queue.shift()!;
    for (const nxt of out[id] ?? []) {
      depth[nxt] = Math.max(depth[nxt] ?? 0, depth[id] + 1);
      if (!seen.has(nxt)) { seen.add(nxt); queue.push(nxt); }
    }
  }
  let maxD = 0;
  for (const n of nodes) {
    if (!(n.id in depth)) depth[n.id] = 0;
    maxD = Math.max(maxD, depth[n.id]);
  }
  const lanes: Record<number, number> = {};
  return nodes.map((n) => {
    const d = depth[n.id];
    const row = lanes[d] ?? 0;
    lanes[d] = row + 1;
    return {
      id: n.id,
      type: "dnode",
      position: { x: d * 250, y: row * 110 },
      data: {
        label: n.name,
        meta: `${n.type} · ${n.request_count} req`,
        status: n.status,
      },
    };
  });
}

function handleFor(index: number, total: number): { sh: string; th: string } {
  void index; void total;
  return { sh: "r", th: "l" };
}

export default function DashGraph({
  nodes,
  edges,
  selected,
  onSelect,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const flowNodes = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const flowEdges: Edge<PulseData>[] = useMemo(
    () =>
      edges.map((e, i) => {
        const err = e.error_rate > 0;
        const { sh, th } = handleFor(i, edges.length);
        return {
          id: `e-${e.source}-${e.target}-${i}`,
          source: e.source,
          sourceHandle: sh,
          target: e.target,
          targetHandle: th,
          type: "pulse",
          label: `${e.request_count} req · ${Math.round(e.error_rate * 100)}% err`,
          data: {
            color: err ? "#ff6b61" : "#c6cdd8",
            dur: `${(1.6 + (i % 5) * 0.35).toFixed(2)}s`,
          },
        };
      }),
    [edges]
  );

  if (!nodes.length) return <div className="empty">No services yet — send telemetry to light up the graph.</div>;

  return (
    <div className="dash-graph">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges.map((e) => ({
          ...e,
          markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15, color: "#565e6c" },
          style: { stroke: "#565e6c", strokeWidth: 1.5 },
        }))}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={(_, n) => onSelect(n.id === selected ? null : n.id)}
        onPaneClick={() => onSelect(null)}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        minZoom={0.4}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: false }}
      >
        <Background gap={26} size={1.4} color="rgba(255,255,255,0.06)" />
      </ReactFlow>
    </div>
  );
}
