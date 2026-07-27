"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ArchiveRestore, CheckCircle2, DatabaseBackup, HardDriveDownload, RotateCcw, ShieldAlert } from "lucide-react";

const plans = [
  { id: "postgres", name: "PostgreSQL", lastBackup: "12 minutes ago", retention: "30 days", status: "healthy" },
  { id: "runtime", name: "Runtime State", lastBackup: "18 minutes ago", retention: "14 days", status: "healthy" },
  { id: "secrets", name: "Secrets Vault", lastBackup: "1 hour ago", retention: "90 days", status: "protected" },
  { id: "artifacts", name: "Project Artifacts", lastBackup: "3 hours ago", retention: "60 days", status: "healthy" },
];

export default function OwnerRecoveryPage() {
  const [action, setAction] = useState<string | null>(null);

  function runAction(label: string) {
    setAction(`${label} request accepted and recorded in the owner audit trail.`);
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="inline-flex items-center gap-2 rounded-full border border-blue-500/20 bg-blue-500/10 px-3 py-1 text-xs text-blue-300"><ArchiveRestore className="h-3.5 w-3.5" /> Owner Recovery Center</div>
        <h1 className="mt-3 text-3xl font-bold text-white">Backup, Restore & Disaster Recovery</h1>
        <p className="mt-2 text-sm text-white/45">Owner-level continuity controls for protected backups, restore validation, failover readiness and recovery evidence.</p>
      </motion.div>

      {action && <div className="rounded-xl border border-green-500/20 bg-green-500/10 px-4 py-3 text-sm text-green-300">{action}</div>}

      <div className="grid gap-4 md:grid-cols-3">
        <button onClick={() => runAction("On-demand backup")} className="glass-card p-5 text-left transition hover:bg-white/[0.05]"><DatabaseBackup className="h-6 w-6 text-electric-300" /><h2 className="mt-4 text-sm font-semibold text-white">Create backup</h2><p className="mt-2 text-xs text-white/40">Capture a governed point-in-time backup.</p></button>
        <button onClick={() => runAction("Restore validation")} className="glass-card p-5 text-left transition hover:bg-white/[0.05]"><RotateCcw className="h-6 w-6 text-purple-300" /><h2 className="mt-4 text-sm font-semibold text-white">Validate restore</h2><p className="mt-2 text-xs text-white/40">Test recovery without changing production.</p></button>
        <button onClick={() => runAction("Disaster recovery drill")} className="glass-card p-5 text-left transition hover:bg-white/[0.05]"><ShieldAlert className="h-6 w-6 text-orange-300" /><h2 className="mt-4 text-sm font-semibold text-white">Run DR drill</h2><p className="mt-2 text-xs text-white/40">Exercise failover, evidence and owner approval.</p></button>
      </div>

      <section className="glass-card overflow-hidden">
        <div className="border-b border-white/[0.06] p-5"><h2 className="text-sm font-semibold text-white">Protected assets</h2></div>
        <div className="divide-y divide-white/[0.05]">
          {plans.map((plan) => (
            <div key={plan.id} className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3"><HardDriveDownload className="h-5 w-5 text-electric-300" /><div><p className="text-sm font-medium text-white">{plan.name}</p><p className="mt-1 text-xs text-white/35">Last backup: {plan.lastBackup} · Retention: {plan.retention}</p></div></div>
              <span className="inline-flex items-center gap-1 text-xs text-green-400"><CheckCircle2 className="h-4 w-4" />{plan.status}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
