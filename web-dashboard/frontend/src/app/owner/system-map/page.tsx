"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Bot,
  Database,
  Globe2,
  Network,
  RefreshCw,
  Server,
  ShieldCheck,
  Workflow,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type NodeKind = "region" | "server" | "worker" | "database" | "service";

type SystemNode = {
  id: string;
  name: string;
  kind: NodeKind;
  region: string;
  parent?: string;
  health: string;
  latency: number | null;
  load: number | null;
  connections: number | null;
};

type SummaryCard = {
  label: string;
  value: number;
  icon: React.ElementType;
};

const icons: Record<NodeKind, React.ElementType> = {
  region: Globe2,
  server: Server,
  worker: Bot,
  database: Database,
  service: Workflow,
};

function healthClass(health: string) {
  if (health === "healthy")
    return "border-green-500/20 bg-green-500/10 text-green-400";
  if (health === "warning")
    return "border-orange-500/20 bg-orange-500/10 text-orange-300";
  if (health === "critical")
    return "border-red-500/20 bg-red-500/10 text-red-400";
  return "border-white/10 bg-white/[0.03] text-white/35";
}

export default function OwnerSystemMapPage() {
  const { items, loading, busy, message, execute } =
    useOwnerResource<SystemNode>("system-map");
  const [selectedRegion, setSelectedRegion] = useState("all");

  const regions = useMemo(
    () => ["all", ...Array.from(new Set(items.map((node) => node.region)))],
    [items],
  );
  const visible = useMemo(
    () =>
      selectedRegion === "all"
        ? items
        : items.filter((node) => node.region === selectedRegion),
    [items, selectedRegion],
  );

  const summaryCards: SummaryCard[] = [
    { label: "Nodes", value: items.length, icon: Network },
    {
      label: "Healthy",
      value: items.filter((node) => node.health === "healthy").length,
      icon: ShieldCheck,
    },
    {
      label: "Warnings",
      value: items.filter((node) => node.health === "warning").length,
      icon: Activity,
    },
    {
      label: "Critical",
      value: items.filter((node) => node.health === "critical").length,
      icon: AlertTriangle,
    },
    {
      label: "Offline",
      value: items.filter((node) => node.health === "offline").length,
      icon: Server,
    },
  ];

  function refreshMap() {
    void execute("all", "refresh");
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <Network className="h-3.5 w-3.5" /> Owner System Map
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Backend Dependency Topology
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Latest backend-reported dependency nodes and health. Refresh to
            request a new snapshot.
          </p>
        </div>
        <button
          onClick={refreshMap}
          disabled={loading || busy}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh topology
        </button>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {summaryCards.map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="glass-card p-4">
              <Icon className="h-5 w-5 text-electric-300" />
              <div className="mt-3 text-2xl font-bold text-white">
                {card.value}
              </div>
              <div className="text-xs text-white/35">{card.label}</div>
            </div>
          );
        })}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-2 text-xs text-electric-300">
            <Activity className="h-3.5 w-3.5" />
            {loading ? "Loading topology snapshot..." : message}
          </div>
          <select
            value={selectedRegion}
            onChange={(event) => setSelectedRegion(event.target.value)}
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            {regions.map((region) => (
              <option key={region} value={region} className="bg-space-800">
                {region === "all" ? "All reported regions" : region}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-3">
        {!loading && visible.length === 0 && (
          <div className="glass-card p-6 text-sm text-white/45">
            No topology nodes match the selected region.
          </div>
        )}
        {visible.map((node, index) => {
          const Icon = icons[node.kind] ?? Network;
          return (
            <motion.div
              key={node.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.03 }}
              className="glass-card p-5"
            >
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex items-start gap-3">
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                    <Icon className="h-5 w-5 text-electric-300" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-white">
                      {node.name}
                    </h2>
                    <p className="mt-1 text-xs text-white/40">
                      {node.kind} · {node.region}
                      {node.parent ? ` · Parent: ${node.parent}` : ""}
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="rounded-lg bg-white/[0.02] px-3 py-2 text-xs text-white/40">
                    Latency{" "}
                    <span className="ml-1 font-semibold text-white">
                      {node.latency === null
                        ? "Unavailable"
                        : `${node.latency}ms`}
                    </span>
                  </div>
                  <div className="rounded-lg bg-white/[0.02] px-3 py-2 text-xs text-white/40">
                    Load{" "}
                    <span className="ml-1 font-semibold text-white">
                      {node.load === null ? "Unavailable" : `${node.load}%`}
                    </span>
                  </div>
                  <div className="rounded-lg bg-white/[0.02] px-3 py-2 text-xs text-white/40">
                    Links{" "}
                    <span className="ml-1 font-semibold text-white">
                      {node.connections === null
                        ? "Unavailable"
                        : node.connections}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-full border px-2.5 py-1 text-xs ${healthClass(
                        node.health,
                      )}`}
                    >
                      {node.health}
                    </span>
                  </div>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
