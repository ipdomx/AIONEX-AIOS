"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  Clock3,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  decideOwnerApproval,
  fetchOwnerApprovals,
  type ApprovalStatus,
  type OwnerApproval,
} from "@/lib/owner-approvals";

export default function OwnerApprovalsLivePage() {
  const [items, setItems] = useState<OwnerApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading owner approvals...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const approvals = await fetchOwnerApprovals(signal);
      setItems(approvals);
      setMessage(
        `Loaded ${approvals.length} approval request${approvals.length === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage("Approval synchronization failed.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  const pending = useMemo(
    () => items.filter((item) => item.status === "pending").length,
    [items],
  );

  async function decide(
    item: OwnerApproval,
    status: Exclude<ApprovalStatus, "pending">,
  ) {
    setMessage(`Applying ${status} decision to ${item.title}...`);
    try {
      const updated = await decideOwnerApproval(item.id, {
        status,
        reason: `Owner decision: ${status}`,
      });
      setItems((current) =>
        current.map((entry) => (entry.id === item.id ? updated : entry)),
      );
      setMessage(`Decision recorded: ${item.title} → ${status}.`);
    } catch {
      setMessage("Approval decision failed and was not persisted.");
    }
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <ShieldCheck className="h-3.5 w-3.5" /> Owner Approval Engine
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Protected Approval Workflow
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Live owner decisions for releases, services, policies, meetings and
            staff actions.
          </p>
        </div>
        <button
          disabled={loading}
          onClick={() => void load()}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="glass-card p-5">
          <Clock3 className="h-5 w-5 text-orange-300" />
          <div className="mt-4 text-3xl font-bold text-white">{pending}</div>
          <div className="mt-1 text-xs text-white/40">
            Pending owner decisions
          </div>
        </div>
        <div className="glass-card p-5">
          <CheckCircle2 className="h-5 w-5 text-green-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {items.filter((item) => item.status === "approved").length}
          </div>
          <div className="mt-1 text-xs text-white/40">Approved</div>
        </div>
        <div className="glass-card p-5">
          <XCircle className="h-5 w-5 text-red-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {items.filter((item) => item.status === "rejected").length}
          </div>
          <div className="mt-1 text-xs text-white/40">Rejected</div>
        </div>
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="space-y-4">
        {items.map((item, index) => (
          <motion.div
            key={item.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            className="glass-card p-5"
          >
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <h2 className="text-sm font-semibold text-white">
                  {item.title}
                </h2>
                <p className="mt-1 text-xs text-white/40">
                  {item.requester} · {item.scope} · {item.category}
                </p>
                <p className="mt-2 text-[11px] text-white/30">
                  Priority: {item.priority} · {item.createdAt}
                </p>
              </div>
              <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs text-white/60">
                {item.status}
              </span>
            </div>
            {item.status === "pending" && (
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  onClick={() => void decide(item, "approved")}
                  className="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300"
                >
                  Approve
                </button>
                <button
                  onClick={() => void decide(item, "changes_requested")}
                  className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300"
                >
                  Request changes
                </button>
                <button
                  onClick={() => void decide(item, "rejected")}
                  className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300"
                >
                  Reject
                </button>
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </div>
  );
}
