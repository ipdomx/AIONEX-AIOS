"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, Bot, CheckCircle2, FolderKanban, Gauge, Server, ShieldCheck, Users, Workflow } from "lucide-react";

const metrics = [
  { label: "Active projects", value: "12", icon: FolderKanban, href: "/owner/projects" },
  { label: "Internal staff", value: "156", icon: Users, href: "/owner/staff" },
  { label: "AI agents", value: "156", icon: Bot, href: "/ai/agents" },
  { label: "Running workflows", value: "89", icon: Workflow, href: "/workflows" },
  { label: "Servers online", value: "42", icon: Server, href: "/infrastructure/servers" },
  { label: "Open incidents", value: "3", icon: AlertTriangle, href: "/owner/incidents" },
];

const readiness = [
  ["Identity and access", "Ready"],
  ["Projects and workflows", "Ready"],
  ["AI workforce", "Ready"],
  ["Infrastructure", "Ready"],
  ["Security and audit", "Ready"],
  ["Backup and recovery", "Ready"],
];

export default function OwnerExecutivePage() {
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><Gauge className="h-3.5 w-3.5" />Owner Executive Overview</div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Enterprise Command Summary</h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">Final owner-level visibility across projects, workforce, infrastructure, AI operations, security, governance, incidents and recovery.</p>
        </div>
        <Link href="/owner/approvals" className="btn-primary">Review pending approvals</Link>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {metrics.map((item, index) => {
          const Icon = item.icon;
          return <motion.div key={item.label} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }}><Link href={item.href} className="glass-card block p-5 transition hover:bg-white/[0.05]"><div className="flex items-center justify-between"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div><span className="text-2xl font-bold text-white">{item.value}</span></div><p className="mt-4 text-xs uppercase tracking-wider text-white/35">{item.label}</p></Link></motion.div>;
        })}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="glass-card p-5">
          <div className="mb-4 flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-green-400" /><h2 className="text-sm font-semibold text-white">Enterprise readiness</h2></div>
          <div className="space-y-3">{readiness.map(([name, state]) => <div key={name} className="flex items-center justify-between rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3"><span className="text-xs text-white/55">{name}</span><span className="inline-flex items-center gap-1 text-xs text-green-400"><CheckCircle2 className="h-3.5 w-3.5" />{state}</span></div>)}</div>
        </section>
        <section className="glass-card p-5">
          <div className="mb-4 flex items-center gap-2"><Activity className="h-5 w-5 text-electric-300" /><h2 className="text-sm font-semibold text-white">Owner priorities</h2></div>
          <div className="space-y-3">
            {["Approve production release", "Review critical infrastructure incident", "Confirm organization service limits", "Validate latest recovery drill"].map((item, index) => <div key={item} className="flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3"><span className="flex h-6 w-6 items-center justify-center rounded-lg bg-electric-500/10 text-xs font-bold text-electric-300">{index + 1}</span><span className="text-xs text-white/60">{item}</span></div>)}
          </div>
        </section>
      </div>
    </div>
  );
}
