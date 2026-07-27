"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, Bot, Database, Globe2, Network, RefreshCw, Server, ShieldCheck, Workflow } from "lucide-react";

type NodeKind = "region" | "server" | "worker" | "database" | "service";
type Health = "healthy" | "warning" | "critical" | "offline";

type SystemNode = {
  id: string;
  name: string;
  kind: NodeKind;
  region: string;
  parent?: string;
  health: Health;
  latency: number;
  load: number;
  connections: number;
};

const initialNodes: SystemNode[] = [
  { id: "region-dubai", name: "Dubai Region", kind: "region", region: "Dubai", health: "healthy", latency: 18, load: 46, connections: 34 },
  { id: "srv-api-01", name: "api-dubai-01", kind: "server", region: "Dubai", parent: "region-dubai", health: "healthy", latency: 21, load: 58, connections: 18 },
  { id: "worker-ai-01", name: "ai-worker-dubai-01", kind: "worker", region: "Dubai", parent: "srv-api-01", health: "warning", latency: 42, load: 84, connections: 9 },
  { id: "db-main-01", name: "postgres-primary", kind: "database", region: "Dubai", parent: "region-dubai", health: "healthy", latency: 12, load: 63, connections: 41 },
  { id: "service-auth", name: "Authentication", kind: "service", region: "Global", parent: "srv-api-01", health: "healthy", latency: 19, load: 39, connections: 27 },
  { id: "region-eu", name: "Europe Region", kind: "region", region: "Frankfurt", health: "warning", latency: 61, load: 72, connections: 17 },
  { id: "srv-eu-02", name: "worker-eu-02", kind: "server", region: "Frankfurt", parent: "region-eu", health: "critical", latency: 138, load: 96, connections: 4 },
  { id: "service-notify", name: "Notifications", kind: "service", region: "Global", parent: "region-eu", health: "offline", latency: 0, load: 0, connections: 0 },
];

const icons = {
  region: Globe2,
  server: Server,
  worker: Bot,
  database: Database,
  service: Workflow,
};

const healthClass: Record<Health, string> = {
  healthy: "border-green-500/20 bg-green-500/10 text-green-400",
  warning: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  critical: "border-red-500/20 bg-red-500/10 text-red-400",
  offline: "border-white/10 bg-white/[0.03] text-white/35",
};

export default function OwnerSystemMapPage() {
  const [nodes, setNodes] = useState(initialNodes);
  const [selectedRegion, setSelectedRegion] = useState("all");
  const [message, setMessage] = useState("Live topology synchronized.");

  const regions = useMemo(() => ["all", ...Array.from(new Set(nodes.map((node) => node.region)))], [nodes]);
  const visible = useMemo(() => selectedRegion === "all" ? nodes : nodes.filter((node) => node.region === selectedRegion), [nodes, selectedRegion]);

  function refreshMap() {
    setNodes((items) => items.map((node) => ({
      ...node,
      latency: node.health === "offline" ? 0 : Math.max(8, node.latency + (node.load > 80 ? 4 : -2)),
      connections: node.health === "offline" ? 0 : Math.max(1, node.connections + 1),
    })));
    setMessage("Topology refreshed and health signals recalculated.");
  }

  function recoverNode(id: string) {
    setNodes((items) => items.map((node) => node.id === id ? { ...node, health: "warning", latency: 75, load: 55, connections: Math.max(1, node.connections) } : node));
    setMessage(`Recovery command issued for ${id}.`);
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><Network className="h-3.5 w-3.5" /> Owner Live System Map</div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Live Infrastructure & Service Topology</h1>
          <p className="mt-2 text-sm text-white/45">Real-time owner visibility across regions, servers, workers, databases and platform services.</p>
        </div>
        <button onClick={refreshMap} className="btn-primary"><RefreshCw className="h-4 w-4" />Refresh topology</button>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {[
          ["Nodes", nodes.length, Network],
          ["Healthy", nodes.filter((node) => node.health === "healthy").length, ShieldCheck],
          ["Warnings", nodes.filter((node) => node.health === "warning").length, Activity],
          ["Critical", nodes.filter((node) => node.health === "critical").length, AlertTriangle],
          ["Offline", nodes.filter((node) => node.health === "offline").length, Server],
        ].map(([label, value, Icon]) => (
          <div key={String(label)} className="glass-card p-4"><Icon className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">{String(value)}</div><div className="text-xs text-white/35">{String(label)}</div></div>
        ))}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-2 text-xs text-electric-300"><Activity className="h-3.5 w-3.5" />{message}</div>
          <select value={selectedRegion} onChange={(event) => setSelectedRegion(event.target.value)} className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none">
            {regions.map((region) => <option key={region} value={region} className="bg-space-800">{region === "all" ? "All regions" : region}</option>)}
          </select>
        </div>
      </div>

      <div className="space-y-3">
        {visible.map((node, index) => {
          const Icon = icons[node.kind];
          return (
            <motion.div key={node.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className="glass-card p-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex items-start gap-3">
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div>
                  <div><h2 className="text-sm font-semibold text-white">{node.name}</h2><p className="mt-1 text-xs text-white/40">{node.kind} · {node.region}{node.parent ? ` · Parent: ${node.parent}` : ""}</p></div>
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="rounded-lg bg-white/[0.02] px-3 py-2 text-xs text-white/40">Latency <span className="ml-1 font-semibold text-white">{node.latency}ms</span></div>
                  <div className="rounded-lg bg-white/[0.02] px-3 py-2 text-xs text-white/40">Load <span className="ml-1 font-semibold text-white">{node.load}%</span></div>
                  <div className="rounded-lg bg-white/[0.02] px-3 py-2 text-xs text-white/40">Links <span className="ml-1 font-semibold text-white">{node.connections}</span></div>
                  <div className="flex items-center gap-2"><span className={`rounded-full border px-2.5 py-1 text-xs ${healthClass[node.health]}`}>{node.health}</span>{node.health !== "healthy" && <button onClick={() => recoverNode(node.id)} className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300">Recover</button>}</div>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
