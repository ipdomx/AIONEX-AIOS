"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, Clock, FileCheck2, ShieldAlert, XCircle } from "lucide-react";

type ApprovalStatus = "pending" | "approved" | "rejected";

type Approval = {
  id: string;
  title: string;
  type: string;
  requester: string;
  risk: "low" | "medium" | "high";
  createdAt: string;
  status: ApprovalStatus;
};

const initialApprovals: Approval[] = [
  { id: "approval-1", title: "Production release for AIOS web dashboard", type: "Release", requester: "Chief Engineer", risk: "high", createdAt: "Today", status: "pending" },
  { id: "approval-2", title: "Enable new OpenRouter provider", type: "AI Provider", requester: "AI Platform Manager", risk: "medium", createdAt: "Today", status: "pending" },
  { id: "approval-3", title: "Create paid engineer session", type: "Meeting", requester: "Operations Manager", risk: "low", createdAt: "Yesterday", status: "pending" },
  { id: "approval-4", title: "Rotate production infrastructure secrets", type: "Security", requester: "Security Center", risk: "high", createdAt: "Yesterday", status: "approved" },
];

export default function OwnerApprovalsPage() {
  const [approvals, setApprovals] = useState(initialApprovals);

  function decide(id: string, status: ApprovalStatus) {
    setApprovals((current) => current.map((item) => (item.id === id ? { ...item, status } : item)));
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-orange-500/20 bg-orange-500/10 px-3 py-1 text-xs text-orange-300"><ShieldAlert className="h-3.5 w-3.5" /> Owner-only control</div>
        <h1 className="text-2xl font-bold text-white">Approvals Center</h1>
        <p className="mt-1 text-sm text-white/40">Review releases, meetings, services, sensitive infrastructure actions and governance decisions.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="glass-card p-5"><p className="text-xs text-white/35">Pending</p><p className="mt-2 text-2xl font-bold text-white">{approvals.filter((item) => item.status === "pending").length}</p></div>
        <div className="glass-card p-5"><p className="text-xs text-white/35">Approved</p><p className="mt-2 text-2xl font-bold text-green-400">{approvals.filter((item) => item.status === "approved").length}</p></div>
        <div className="glass-card p-5"><p className="text-xs text-white/35">Rejected</p><p className="mt-2 text-2xl font-bold text-red-400">{approvals.filter((item) => item.status === "rejected").length}</p></div>
      </div>

      <div className="space-y-3">
        {approvals.map((item, index) => (
          <motion.div key={item.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-start gap-3">
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-2.5"><FileCheck2 className="h-5 w-5 text-electric-300" /></div>
                <div>
                  <div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold text-white">{item.title}</h2><span className={`rounded-full border px-2 py-0.5 text-[10px] ${item.risk === "high" ? "border-red-500/20 bg-red-500/10 text-red-300" : item.risk === "medium" ? "border-orange-500/20 bg-orange-500/10 text-orange-300" : "border-green-500/20 bg-green-500/10 text-green-300"}`}>{item.risk} risk</span></div>
                  <p className="mt-1 text-xs text-white/40">{item.type} · Requested by {item.requester} · {item.createdAt}</p>
                </div>
              </div>

              {item.status === "pending" ? (
                <div className="flex gap-2">
                  <button onClick={() => decide(item.id, "rejected")} className="inline-flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-2 text-xs font-medium text-red-300 transition hover:bg-red-500/20"><XCircle className="h-4 w-4" />Reject</button>
                  <button onClick={() => decide(item.id, "approved")} className="inline-flex items-center gap-2 rounded-xl border border-green-500/20 bg-green-500/10 px-4 py-2 text-xs font-medium text-green-300 transition hover:bg-green-500/20"><CheckCircle2 className="h-4 w-4" />Approve</button>
                </div>
              ) : (
                <div className={`inline-flex items-center gap-2 text-xs font-medium ${item.status === "approved" ? "text-green-400" : "text-red-400"}`}>{item.status === "approved" ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}{item.status}</div>
              )}
            </div>
          </motion.div>
        ))}
      </div>

      <div className="glass-card flex items-center gap-3 p-4 text-xs text-white/45"><Clock className="h-4 w-4 text-electric-300" />Every decision is intended to be recorded in the owner audit trail.</div>
    </div>
  );
}
