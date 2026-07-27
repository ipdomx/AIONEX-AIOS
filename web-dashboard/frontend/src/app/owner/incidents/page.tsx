"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Clock3, Flame, Server, ShieldAlert, Siren } from "lucide-react";

type Incident = {
  id: string;
  title: string;
  source: string;
  severity: "critical" | "high" | "medium";
  status: "open" | "investigating" | "resolved";
  owner: string;
  updated: string;
};

const initialIncidents: Incident[] = [
  { id: "INC-1042", title: "Repeated authentication failures", source: "Security Gateway", severity: "critical", status: "investigating", owner: "Security Council", updated: "2 minutes ago" },
  { id: "INC-1041", title: "Database memory pressure", source: "PostgreSQL Primary", severity: "high", status: "open", owner: "Infrastructure Ministry", updated: "9 minutes ago" },
  { id: "INC-1039", title: "Worker queue latency", source: "Distributed Runtime", severity: "medium", status: "investigating", owner: "Runtime Operations", updated: "24 minutes ago" },
  { id: "INC-1036", title: "Provider timeout threshold exceeded", source: "AI Router", severity: "high", status: "resolved", owner: "AI Operations", updated: "1 hour ago" },
];

const severityStyle = {
  critical: "border-red-500/25 bg-red-500/10 text-red-300",
  high: "border-orange-500/25 bg-orange-500/10 text-orange-300",
  medium: "border-yellow-500/25 bg-yellow-500/10 text-yellow-300",
};

export default function OwnerIncidentsPage() {
  const [incidents, setIncidents] = useState(initialIncidents);

  function updateStatus(id: string, status: Incident["status"]) {
    setIncidents((current) => current.map((incident) => incident.id === id ? { ...incident, status, updated: "Just now" } : incident));
  }

  const openCount = incidents.filter((incident) => incident.status !== "resolved").length;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-red-500/20 bg-red-500/10 px-3 py-1 text-xs text-red-300"><Siren className="h-3.5 w-3.5" />Owner Incident Command</div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Incidents & Emergency Response</h1>
          <p className="mt-1 text-sm text-white/40">Owner visibility over platform failures, security events, response teams and resolution state.</p>
        </div>
        <div className="glass-card flex items-center gap-3 px-5 py-3"><ShieldAlert className="h-5 w-5 text-orange-400" /><div><div className="text-lg font-bold text-white">{openCount}</div><div className="text-[10px] uppercase tracking-wider text-white/30">Active incidents</div></div></div>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="glass-card p-5"><Flame className="h-5 w-5 text-red-400" /><div className="mt-3 text-2xl font-bold text-white">{incidents.filter((item) => item.severity === "critical" && item.status !== "resolved").length}</div><div className="text-xs text-white/35">Critical open</div></div>
        <div className="glass-card p-5"><Clock3 className="h-5 w-5 text-orange-400" /><div className="mt-3 text-2xl font-bold text-white">2m</div><div className="text-xs text-white/35">Median acknowledgment</div></div>
        <div className="glass-card p-5"><CheckCircle2 className="h-5 w-5 text-green-400" /><div className="mt-3 text-2xl font-bold text-white">99.8%</div><div className="text-xs text-white/35">Recovery readiness</div></div>
      </div>

      <div className="space-y-3">
        {incidents.map((incident, index) => (
          <motion.div key={incident.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex items-start gap-4">
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">{incident.source.includes("Database") ? <Server className="h-5 w-5 text-electric-300" /> : <AlertTriangle className="h-5 w-5 text-orange-400" />}</div>
                <div>
                  <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-white/35">{incident.id}</span><span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${severityStyle[incident.severity]}`}>{incident.severity}</span><span className="rounded-full border border-white/[0.06] bg-white/[0.03] px-2 py-0.5 text-[10px] text-white/45">{incident.status}</span></div>
                  <h2 className="mt-2 text-sm font-semibold text-white">{incident.title}</h2>
                  <p className="mt-1 text-xs text-white/35">{incident.source} · Owner team: {incident.owner} · {incident.updated}</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => updateStatus(incident.id, "investigating")} className="rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/65 hover:bg-white/[0.08]">Investigate</button>
                <button onClick={() => updateStatus(incident.id, "resolved")} className="rounded-xl border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300 hover:bg-green-500/15">Resolve</button>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
