"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, CheckCircle2, Filter, Search, ShieldCheck, UserRound } from "lucide-react";

type AuditEvent = {
  id: string;
  actor: string;
  action: string;
  target: string;
  severity: "info" | "warning" | "critical";
  status: "completed" | "blocked" | "pending";
  timestamp: string;
};

const initialEvents: AuditEvent[] = [
  { id: "evt-1", actor: "AIONEX Owner", action: "Approved production release", target: "AIOS Runtime", severity: "info", status: "completed", timestamp: "2 minutes ago" },
  { id: "evt-2", actor: "Chief Engineer", action: "Requested infrastructure exception", target: "prod-worker-02", severity: "warning", status: "pending", timestamp: "18 minutes ago" },
  { id: "evt-3", actor: "Security Council", action: "Blocked suspicious provider key rotation", target: "OpenRouter", severity: "critical", status: "blocked", timestamp: "34 minutes ago" },
  { id: "evt-4", actor: "Operations Manager", action: "Completed disaster recovery drill", target: "Primary Region", severity: "info", status: "completed", timestamp: "1 hour ago" },
  { id: "evt-5", actor: "AIONEX Owner", action: "Updated organization service policy", target: "AIONEX Corp", severity: "info", status: "completed", timestamp: "3 hours ago" },
];

export default function OwnerAuditPage() {
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("all");

  const events = useMemo(
    () => initialEvents.filter((event) => {
      const text = `${event.actor} ${event.action} ${event.target}`.toLowerCase();
      return text.includes(query.toLowerCase()) && (severity === "all" || event.severity === severity);
    }),
    [query, severity],
  );

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300"><ShieldCheck className="h-3.5 w-3.5" /> Owner Audit Command</div>
        <h1 className="mt-3 text-3xl font-bold text-white">Owner Audit & Accountability</h1>
        <p className="mt-2 text-sm text-white/45">Full visibility into owner decisions, approvals, internal staff actions, policy changes, incidents and governance events.</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[{ label: "Tracked Events", value: initialEvents.length, icon: Activity }, { label: "Pending Review", value: initialEvents.filter((item) => item.status === "pending").length, icon: AlertTriangle }, { label: "Completed", value: initialEvents.filter((item) => item.status === "completed").length, icon: CheckCircle2 }].map((item) => {
          const Icon = item.icon;
          return <div key={item.label} className="glass-card p-5"><div className="flex items-center justify-between"><Icon className="h-5 w-5 text-electric-300" /><span className="text-2xl font-bold text-white">{item.value}</span></div><p className="mt-3 text-xs uppercase tracking-wider text-white/35">{item.label}</p></div>;
        })}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="relative flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search actor, action or target..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" /></div>
          <div className="flex items-center gap-2"><Filter className="h-4 w-4 text-white/35" /><select value={severity} onChange={(event) => setSeverity(event.target.value)} className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"><option value="all" className="bg-space-800">All severity</option><option value="info" className="bg-space-800">Info</option><option value="warning" className="bg-space-800">Warning</option><option value="critical" className="bg-space-800">Critical</option></select></div>
        </div>
      </div>

      <div className="space-y-3">
        {events.map((event, index) => (
          <motion.div key={event.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-start gap-3"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><UserRound className="h-4 w-4 text-electric-300" /></div><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold text-white">{event.actor}</h2><span className={`rounded-full border px-2 py-0.5 text-[10px] ${event.severity === "critical" ? "border-red-500/20 bg-red-500/10 text-red-300" : event.severity === "warning" ? "border-orange-500/20 bg-orange-500/10 text-orange-300" : "border-blue-500/20 bg-blue-500/10 text-blue-300"}`}>{event.severity}</span></div><p className="mt-1 text-xs text-white/55">{event.action}</p><p className="mt-1 text-[11px] text-white/30">Target: {event.target}</p></div></div>
              <div className="flex items-center gap-3"><span className="text-[11px] text-white/30">{event.timestamp}</span><span className={`rounded-full border px-2.5 py-1 text-[10px] ${event.status === "completed" ? "border-green-500/20 bg-green-500/10 text-green-300" : event.status === "blocked" ? "border-red-500/20 bg-red-500/10 text-red-300" : "border-orange-500/20 bg-orange-500/10 text-orange-300"}`}>{event.status}</span></div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
