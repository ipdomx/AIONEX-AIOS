"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, CheckCircle2, Database, HardDrive, Network, Server, ShieldCheck } from "lucide-react";

const systems = [
  { name: "Frontend", status: "healthy", detail: "Next.js application responding normally", icon: Activity },
  { name: "Backend API", status: "healthy", detail: "Authenticated API and runtime endpoints available", icon: Server },
  { name: "PostgreSQL", status: "healthy", detail: "Identity and operational database connected", icon: Database },
  { name: "Storage", status: "healthy", detail: "Backup targets and persistent volumes available", icon: HardDrive },
  { name: "Network", status: "healthy", detail: "Gateway and service connectivity operational", icon: Network },
  { name: "Security", status: "attention", detail: "Three owner-reviewed alerts remain open", icon: ShieldCheck },
];

export default function OwnerHealthPage() {
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Owner System Health</h1>
          <p className="mt-2 text-sm text-white/45">Central readiness and health verification for the complete AIONEX AIOS control plane.</p>
        </div>
        <Link href="/owner/incidents" className="btn-primary">Open incident command</Link>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {systems.map((system, index) => {
          const Icon = system.icon;
          const healthy = system.status === "healthy";
          return (
            <motion.section key={system.name} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div><div><h2 className="text-sm font-semibold text-white">{system.name}</h2><p className="mt-1 text-xs text-white/40">{system.detail}</p></div></div>
                <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-medium ${healthy ? "border-green-500/20 bg-green-500/10 text-green-400" : "border-orange-500/20 bg-orange-500/10 text-orange-400"}`}>{healthy ? <CheckCircle2 className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}{healthy ? "Healthy" : "Attention"}</span>
              </div>
            </motion.section>
          );
        })}
      </div>

      <section className="glass-card p-5">
        <div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-semibold text-white">Owner validation checklist</h2><span className="text-xs text-green-400">6 / 6 verified</span></div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{["Authentication and owner access", "Projects and organization scope", "AI providers and agents", "Infrastructure and monitoring", "Audit and notifications", "Backup and disaster recovery"].map((item) => <div key={item} className="flex items-center gap-2 rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3 text-xs text-white/60"><CheckCircle2 className="h-4 w-4 text-green-400" />{item}</div>)}</div>
      </section>
    </div>
  );
}
