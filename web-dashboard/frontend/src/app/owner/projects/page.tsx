"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, FolderKanban, PauseCircle, PlayCircle, Search, ShieldCheck } from "lucide-react";

const projects = [
  { name: "AIOS Runtime", owner: "AIONEX Owner", organization: "AIONEX Corp", status: "active", risk: "low", progress: 84, approvals: 1 },
  { name: "Enterprise Notifications", owner: "Operations Council", organization: "AIONEX Corp", status: "review", risk: "medium", progress: 71, approvals: 3 },
  { name: "Distributed Workers", owner: "Chief Engineer", organization: "AIONEX Labs", status: "planning", risk: "high", progress: 22, approvals: 2 },
  { name: "Mobile Clients", owner: "Product Ministry", organization: "AIONEX Corp", status: "paused", risk: "medium", progress: 39, approvals: 4 },
];

export default function OwnerProjectsPage() {
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300"><FolderKanban className="h-3.5 w-3.5" /> Owner Project Command</div>
          <h1 className="text-3xl font-bold text-white">Global Project Oversight</h1>
          <p className="mt-2 text-sm text-white/45">Owner visibility across every project, organization, approval, risk and execution state.</p>
        </div>
        <Link href="/projects?create=1" className="btn-primary">Create governed project</Link>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Total projects", "12"],
          ["Needs approval", "7"],
          ["High risk", "2"],
          ["Paused by owner", "1"],
        ].map(([label, value]) => <div key={label} className="glass-card p-5"><div className="text-2xl font-bold text-white">{value}</div><div className="mt-1 text-xs text-white/35">{label}</div></div>)}
      </div>

      <section className="glass-card p-5">
        <div className="mb-4 flex items-center gap-3"><Search className="h-4 w-4 text-white/30" /><input className="glass-input w-full rounded-xl px-4 py-2.5 text-sm text-white outline-none" placeholder="Search every project..." /></div>
        <div className="space-y-3">
          {projects.map((project) => (
            <div key={project.name} className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div>
                  <div className="flex items-center gap-2"><h2 className="text-sm font-semibold text-white">{project.name}</h2>{project.risk === "high" ? <AlertTriangle className="h-4 w-4 text-red-400" /> : <ShieldCheck className="h-4 w-4 text-green-400" />}</div>
                  <p className="mt-1 text-xs text-white/40">{project.organization} · {project.owner}</p>
                </div>
                <div className="grid flex-1 grid-cols-2 gap-3 sm:grid-cols-4 xl:max-w-2xl">
                  <div><div className="text-[10px] uppercase text-white/25">Status</div><div className="mt-1 text-xs text-white/65">{project.status}</div></div>
                  <div><div className="text-[10px] uppercase text-white/25">Progress</div><div className="mt-1 text-xs text-white/65">{project.progress}%</div></div>
                  <div><div className="text-[10px] uppercase text-white/25">Approvals</div><div className="mt-1 text-xs text-white/65">{project.approvals}</div></div>
                  <div><div className="text-[10px] uppercase text-white/25">Risk</div><div className="mt-1 text-xs text-white/65">{project.risk}</div></div>
                </div>
                <div className="flex gap-2">
                  <button className="rounded-lg border border-white/[0.08] p-2 text-white/55 hover:bg-white/[0.06]" aria-label="Resume project"><PlayCircle className="h-4 w-4" /></button>
                  <button className="rounded-lg border border-white/[0.08] p-2 text-white/55 hover:bg-white/[0.06]" aria-label="Pause project"><PauseCircle className="h-4 w-4" /></button>
                  <button className="rounded-lg border border-green-500/20 bg-green-500/10 p-2 text-green-400" aria-label="Approve project"><CheckCircle2 className="h-4 w-4" /></button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
