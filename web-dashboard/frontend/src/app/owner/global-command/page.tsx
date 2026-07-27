"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, Bot, Building2, CheckCircle2, FolderKanban, PauseCircle, PlayCircle, Search, Server, ShieldCheck, Users, Workflow, XCircle } from "lucide-react";

type Entity = {
  id: string;
  type: "project" | "organization" | "worker" | "service";
  name: string;
  scope: string;
  status: "active" | "paused" | "warning" | "offline";
  risk: "low" | "medium" | "high" | "critical";
  owner: string;
};

const initialEntities: Entity[] = [
  { id: "project-aios", type: "project", name: "AIONEX AIOS", scope: "Enterprise Core", status: "active", risk: "medium", owner: "AIONEX Owner" },
  { id: "org-aionex", type: "organization", name: "AIONEX Corp", scope: "Global", status: "active", risk: "low", owner: "AIONEX Owner" },
  { id: "worker-01", type: "worker", name: "worker-dubai-01", scope: "Dubai Region", status: "warning", risk: "high", owner: "Infrastructure" },
  { id: "service-auth", type: "service", name: "Authentication Service", scope: "Platform", status: "active", risk: "low", owner: "Security" },
  { id: "service-notify", type: "service", name: "Notification Service", scope: "Platform", status: "paused", risk: "medium", owner: "Operations" },
  { id: "worker-02", type: "worker", name: "worker-eu-02", scope: "Europe Region", status: "offline", risk: "critical", owner: "Infrastructure" },
];

const iconMap = {
  project: FolderKanban,
  organization: Building2,
  worker: Bot,
  service: Server,
};

const statusStyles: Record<Entity["status"], string> = {
  active: "border-green-500/20 bg-green-500/10 text-green-400",
  paused: "border-orange-500/20 bg-orange-500/10 text-orange-400",
  warning: "border-yellow-500/20 bg-yellow-500/10 text-yellow-300",
  offline: "border-red-500/20 bg-red-500/10 text-red-400",
};

const riskStyles: Record<Entity["risk"], string> = {
  low: "text-green-400",
  medium: "text-blue-300",
  high: "text-orange-400",
  critical: "text-red-400",
};

export default function OwnerGlobalCommandPage() {
  const [entities, setEntities] = useState(initialEntities);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | Entity["type"]>("all");
  const [message, setMessage] = useState("Ready for owner command.");

  const filtered = useMemo(() => entities.filter((entity) => {
    const matchesQuery = entity.name.toLowerCase().includes(query.toLowerCase()) || entity.scope.toLowerCase().includes(query.toLowerCase());
    const matchesType = typeFilter === "all" || entity.type === typeFilter;
    return matchesQuery && matchesType;
  }), [entities, query, typeFilter]);

  function updateStatus(id: string, status: Entity["status"]) {
    setEntities((items) => items.map((item) => item.id === id ? { ...item, status } : item));
    setMessage(`Owner command applied: ${id} → ${status}`);
  }

  function runGlobalAction(action: "resume" | "pause" | "validate") {
    if (action === "resume") setEntities((items) => items.map((item) => ({ ...item, status: "active" })));
    if (action === "pause") setEntities((items) => items.map((item) => item.risk === "critical" || item.risk === "high" ? { ...item, status: "paused" } : item));
    if (action === "validate") setEntities((items) => items.map((item) => item.status === "offline" ? { ...item, status: "warning" } : item));
    setMessage(`Global owner action completed: ${action}`);
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><ShieldCheck className="h-3.5 w-3.5" /> Owner Global Command</div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Global Command Center</h1>
          <p className="mt-2 text-sm text-white/45">Execute owner-level controls across projects, organizations, workers and platform services.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => runGlobalAction("resume")} className="btn-primary"><PlayCircle className="h-4 w-4" />Resume all</button>
          <button onClick={() => runGlobalAction("pause")} className="rounded-xl border border-orange-500/20 bg-orange-500/10 px-4 py-2.5 text-sm font-medium text-orange-300"><PauseCircle className="mr-2 inline h-4 w-4" />Pause risky</button>
          <button onClick={() => runGlobalAction("validate")} className="rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-white/75"><CheckCircle2 className="mr-2 inline h-4 w-4" />Validate</button>
        </div>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {[
          ["Projects", entities.filter((item) => item.type === "project").length, FolderKanban],
          ["Organizations", entities.filter((item) => item.type === "organization").length, Users],
          ["Workers", entities.filter((item) => item.type === "worker").length, Bot],
          ["Services", entities.filter((item) => item.type === "service").length, Server],
          ["Critical", entities.filter((item) => item.risk === "critical").length, AlertTriangle],
        ].map(([label, value, Icon]) => (
          <div key={String(label)} className="glass-card p-4"><Icon className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">{String(value)}</div><div className="text-xs text-white/35">{String(label)}</div></div>
        ))}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full max-w-xl"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search every controlled entity..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" /></div>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as typeof typeFilter)} className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"><option value="all" className="bg-space-800">All entities</option><option value="project" className="bg-space-800">Projects</option><option value="organization" className="bg-space-800">Organizations</option><option value="worker" className="bg-space-800">Workers</option><option value="service" className="bg-space-800">Services</option></select>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300"><Activity className="h-3.5 w-3.5" />{message}</div>
      </div>

      <div className="space-y-3">
        {filtered.map((entity, index) => {
          const Icon = iconMap[entity.type];
          return (
            <motion.div key={entity.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className="glass-card p-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex items-start gap-3"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div><div><h2 className="text-sm font-semibold text-white">{entity.name}</h2><p className="mt-1 text-xs text-white/40">{entity.type} · {entity.scope} · Owner: {entity.owner}</p><p className={`mt-2 text-xs font-medium ${riskStyles[entity.risk]}`}>Risk: {entity.risk}</p></div></div>
                <div className="flex flex-wrap items-center gap-2"><span className={`rounded-full border px-2.5 py-1 text-xs ${statusStyles[entity.status]}`}>{entity.status}</span><button onClick={() => updateStatus(entity.id, "active")} className="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300">Activate</button><button onClick={() => updateStatus(entity.id, "paused")} className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300">Pause</button><button onClick={() => updateStatus(entity.id, "offline")} className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300"><XCircle className="mr-1 inline h-3.5 w-3.5" />Stop</button></div>
              </div>
            </motion.div>
          );
        })}
      </div>

      <div className="flex justify-end"><Link href="/owner" className="text-xs text-electric-300">Back to Owner Center</Link></div>
    </div>
  );
}
