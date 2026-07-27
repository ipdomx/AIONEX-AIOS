"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, CircleDashed, PackageCheck, Rocket, ShieldCheck, TestTube2 } from "lucide-react";

const initialGates = [
  { id: "validation", name: "Final Validation", owner: "Chief Engineer", status: "passed" },
  { id: "security", name: "Security Validation", owner: "Security Council", status: "passed" },
  { id: "performance", name: "Performance & Load Tests", owner: "Platform Team", status: "passed" },
  { id: "backup", name: "Backup & Restore Verification", owner: "Operations", status: "passed" },
  { id: "approval", name: "Final Owner Approval", owner: "Owner", status: "pending" },
];

export default function OwnerReleasePage() {
  const [gates, setGates] = useState(initialGates);
  const [releaseStatus, setReleaseStatus] = useState("blocked");
  const pending = gates.some((gate) => gate.status !== "passed");

  function approveRelease() {
    setGates((current) => current.map((gate) => gate.id === "approval" ? { ...gate, status: "passed" } : gate));
    setReleaseStatus("ready");
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div><div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300"><Rocket className="h-3.5 w-3.5" />Owner Release Authority</div><h1 className="text-3xl font-bold text-white">Release Readiness & Final Approval</h1><p className="mt-2 text-sm text-white/45">Final owner gate for production release, rollback readiness and deployment authorization.</p></div>
        <button onClick={approveRelease} disabled={!pending} className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"><ShieldCheck className="h-4 w-4" />{pending ? "Approve Release" : "Release Approved"}</button>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {[{ label: "Validation suites", value: "4/4", icon: TestTube2 }, { label: "Security gates", value: "Passed", icon: ShieldCheck }, { label: "Rollback plan", value: "Ready", icon: PackageCheck }, { label: "Release state", value: releaseStatus === "ready" ? "Ready" : "Blocked", icon: Rocket }].map((item) => <div key={item.label} className="glass-card p-5"><item.icon className="h-5 w-5 text-electric-300" /><div className="mt-4 text-xl font-bold text-white">{item.value}</div><div className="mt-1 text-xs text-white/35">{item.label}</div></div>)}
      </div>

      <section className="glass-card p-5"><h2 className="mb-4 text-sm font-semibold text-white">Mandatory Release Gates</h2><div className="space-y-3">{gates.map((gate) => <div key={gate.id} className="flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] p-4">{gate.status === "passed" ? <CheckCircle2 className="h-5 w-5 text-green-400" /> : <CircleDashed className="h-5 w-5 text-orange-300" />}<div className="flex-1"><div className="text-sm font-medium text-white">{gate.name}</div><div className="mt-1 text-xs text-white/35">Responsible: {gate.owner}</div></div><span className={`rounded-full px-3 py-1 text-xs ${gate.status === "passed" ? "bg-green-500/10 text-green-400" : "bg-orange-500/10 text-orange-300"}`}>{gate.status}</span></div>)}</div></section>
    </div>
  );
}
