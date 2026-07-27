"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, Brain, Briefcase, Search, ShieldCheck, Stethoscope, UserCog, Users } from "lucide-react";

const staff = [
  { id: "chief-engineer", name: "Chief Engineer", department: "Engineering", status: "active", health: "stable", performance: 97, incidents: 0, doctor: "Dr. Nadia" },
  { id: "security-director", name: "Security Director", department: "Defense Intelligence", status: "active", health: "review", performance: 94, incidents: 1, doctor: "Dr. Kareem" },
  { id: "operations-manager", name: "Operations Manager", department: "Infrastructure", status: "active", health: "stable", performance: 91, incidents: 0, doctor: "Dr. Salma" },
  { id: "research-lead", name: "Research Lead", department: "Knowledge Ministry", status: "paused", health: "stable", performance: 89, incidents: 0, doctor: "Dr. Lina" },
];

export default function OwnerStaffPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const visible = useMemo(() => staff.filter((item) => (status === "all" || item.status === status) && `${item.name} ${item.department}`.toLowerCase().includes(query.toLowerCase())), [query, status]);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-purple-500/20 bg-purple-500/10 px-3 py-1 text-xs font-medium text-purple-300"><UserCog className="h-3.5 w-3.5" />Owner Staff Oversight</div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Internal Staff Command</h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">Owner-only visibility into internal roles, departments, performance, incidents, medical oversight and operating status.</p>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[{ label: "Active Staff", value: "3", icon: Users }, { label: "Departments", value: "4", icon: Briefcase }, { label: "Medical Reviews", value: "1", icon: Stethoscope }, { label: "Open Staff Incidents", value: "1", icon: AlertTriangle }].map((item) => <div key={item.label} className="glass-card p-5"><item.icon className="h-5 w-5 text-purple-300" /><div className="mt-4 text-2xl font-bold text-white">{item.value}</div><div className="mt-1 text-xs uppercase tracking-wider text-white/35">{item.label}</div></div>)}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search staff or department..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" /></div>
        <select value={status} onChange={(event) => setStatus(event.target.value)} className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"><option value="all" className="bg-space-800">All Status</option><option value="active" className="bg-space-800">Active</option><option value="paused" className="bg-space-800">Paused</option></select>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {visible.map((member, index) => (
          <motion.section key={member.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-5">
            <div className="flex items-start justify-between gap-4"><div><div className="flex items-center gap-3"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Brain className="h-5 w-5 text-purple-300" /></div><div><h2 className="text-sm font-semibold text-white">{member.name}</h2><p className="text-xs text-white/40">{member.department}</p></div></div></div><span className={`rounded-full border px-2.5 py-1 text-xs ${member.status === "active" ? "border-green-500/20 bg-green-500/10 text-green-400" : "border-orange-500/20 bg-orange-500/10 text-orange-400"}`}>{member.status}</span></div>
            <div className="mt-5 grid grid-cols-2 gap-3 text-xs"><div className="rounded-xl bg-white/[0.02] p-3"><div className="text-white/35">Performance</div><div className="mt-1 text-lg font-bold text-white">{member.performance}%</div></div><div className="rounded-xl bg-white/[0.02] p-3"><div className="text-white/35">Incidents</div><div className="mt-1 text-lg font-bold text-white">{member.incidents}</div></div></div>
            <div className="mt-4 space-y-2 border-t border-white/[0.05] pt-4 text-xs text-white/45"><div className="flex items-center gap-2"><Stethoscope className="h-3.5 w-3.5" />Assigned doctor: {member.doctor}</div><div className="flex items-center gap-2"><ShieldCheck className="h-3.5 w-3.5" />Health status: {member.health}</div><div className="flex items-center gap-2"><Activity className="h-3.5 w-3.5" />Owner visibility enabled</div></div>
          </motion.section>
        ))}
      </div>
    </div>
  );
}
