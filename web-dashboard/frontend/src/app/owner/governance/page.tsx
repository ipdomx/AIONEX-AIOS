"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Building2, CheckCircle2, Gavel, Landmark, Shield, Users, Vote, XCircle } from "lucide-react";

const bodies = [
  { name: "Supreme Owner Council", type: "Council", members: 7, quorum: 5, status: "active" },
  { name: "Engineering Ministry", type: "Ministry", members: 12, quorum: 7, status: "active" },
  { name: "Defense Intelligence Council", type: "Council", members: 9, quorum: 6, status: "restricted" },
  { name: "Knowledge Ministry", type: "Ministry", members: 14, quorum: 8, status: "active" },
];

const initialDecisions = [
  { id: "decision-1", title: "Approve distributed worker expansion", body: "Supreme Owner Council", votes: "6 / 7", status: "pending" },
  { id: "decision-2", title: "Enable new AI provider evaluation", body: "Engineering Ministry", votes: "8 / 12", status: "pending" },
  { id: "decision-3", title: "Approve defensive threat research program", body: "Defense Intelligence Council", votes: "7 / 9", status: "pending" },
];

export default function OwnerGovernancePage() {
  const [decisions, setDecisions] = useState(initialDecisions);
  const resolve = (id: string, result: "approved" | "rejected") => setDecisions((items) => items.map((item) => item.id === id ? { ...item, status: result } : item));

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-300"><Gavel className="h-3.5 w-3.5" />Owner Governance</div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Councils, Ministries & Decisions</h1>
        <p className="mt-2 max-w-3xl text-sm text-white/45">Control organizational bodies, voting, quorum, approvals and owner-level final decisions.</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4">
        {bodies.map((body, index) => <motion.section key={body.name} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-5"><div className="flex items-center justify-between"><div className="rounded-xl bg-amber-500/10 p-2.5"><Landmark className="h-5 w-5 text-amber-300" /></div><span className={`text-xs ${body.status === "active" ? "text-green-400" : "text-orange-400"}`}>{body.status}</span></div><h2 className="mt-4 text-sm font-semibold text-white">{body.name}</h2><p className="mt-1 text-xs text-white/35">{body.type}</p><div className="mt-4 space-y-2 text-xs text-white/45"><div className="flex items-center gap-2"><Users className="h-3.5 w-3.5" />{body.members} members</div><div className="flex items-center gap-2"><Vote className="h-3.5 w-3.5" />Quorum {body.quorum}</div></div></motion.section>)}
      </div>

      <section className="glass-card p-5">
        <div className="mb-4 flex items-center justify-between"><div><h2 className="text-sm font-semibold text-white">Owner Decision Queue</h2><p className="mt-1 text-xs text-white/35">Final owner authority overrides council outcomes when required.</p></div><Shield className="h-5 w-5 text-amber-300" /></div>
        <div className="space-y-3">
          {decisions.map((decision) => <div key={decision.id} className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-4"><div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"><div><h3 className="text-sm font-medium text-white">{decision.title}</h3><p className="mt-1 text-xs text-white/40">{decision.body} · Votes {decision.votes}</p></div>{decision.status === "pending" ? <div className="flex gap-2"><button onClick={() => resolve(decision.id, "approved")} className="inline-flex items-center gap-2 rounded-lg bg-green-500/15 px-3 py-2 text-xs text-green-300 hover:bg-green-500/20"><CheckCircle2 className="h-4 w-4" />Approve</button><button onClick={() => resolve(decision.id, "rejected")} className="inline-flex items-center gap-2 rounded-lg bg-red-500/15 px-3 py-2 text-xs text-red-300 hover:bg-red-500/20"><XCircle className="h-4 w-4" />Reject</button></div> : <span className={`rounded-full px-3 py-1 text-xs ${decision.status === "approved" ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"}`}>{decision.status}</span>}</div></div>)}
        </div>
      </section>

      <section className="glass-card p-5"><div className="flex items-center gap-3"><Building2 className="h-5 w-5 text-amber-300" /><div><h2 className="text-sm font-semibold text-white">Governance Guardrails</h2><p className="mt-1 text-xs text-white/40">Owner approval is mandatory for meetings, service activation, staff suspension, external integrations and high-risk operations.</p></div></div></section>
    </div>
  );
}
