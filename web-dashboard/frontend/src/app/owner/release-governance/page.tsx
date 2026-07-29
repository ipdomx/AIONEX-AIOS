"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  CheckCircle2,
  CircleAlert,
  Clock3,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Undo2,
  XCircle,
} from "lucide-react";
import {
  decideRelease,
  fetchReleaseCandidates,
  type ReleaseCandidate,
} from "@/lib/owner-release-governance";

const statusClass: Record<
  "passed" | "warning" | "blocked" | "pending",
  string
> = {
  passed: "border-green-500/20 bg-green-500/10 text-green-300",
  warning: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  blocked: "border-red-500/20 bg-red-500/10 text-red-300",
  pending: "border-blue-500/20 bg-blue-500/10 text-blue-300",
};

type SummaryCard = { label: string; value: number; icon: LucideIcon };

export default function OwnerReleaseGovernancePage() {
  const [items, setItems] = useState<ReleaseCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading release governance...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchReleaseCandidates(signal);
      setItems(data);
      setMessage("Release candidates synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setItems([]);
        setMessage("Release governance backend contract is not available.");
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

  const summary = useMemo(
    () => ({
      ready: items.filter((item) => item.status === "ready").length,
      blocked: items.filter((item) => item.status === "blocked").length,
      pendingOwner: items.filter((item) =>
        item.gates.some(
          (gate) => gate.ownerRequired && gate.status === "pending",
        ),
      ).length,
    }),
    [items],
  );

  const cards: SummaryCard[] = [
    { label: "Ready", value: summary.ready, icon: CheckCircle2 },
    { label: "Blocked", value: summary.blocked, icon: XCircle },
    { label: "Owner action", value: summary.pendingOwner, icon: Clock3 },
  ];

  async function act(id: string, decision: "approve" | "reject" | "rollback") {
    setMessage(`Submitting ${decision} decision...`);
    try {
      const updated = await decideRelease(
        id,
        decision,
        "Owner decision from release governance center",
      );
      setItems((current) =>
        current.map((item) => (item.id === id ? updated : item)),
      );
      setMessage(`Release decision completed: ${decision}.`);
    } catch {
      setMessage("Release decision failed and was not persisted.");
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
            <Rocket className="h-3.5 w-3.5" /> Owner Release Governance
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Release Authority & Quality Gates
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Final owner authority for production releases, quality gates,
            rejection and rollback.
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
        {cards.map(({ label, value, icon: Icon }) => (
          <div key={label} className="glass-card p-5">
            <Icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-3xl font-bold text-white">{value}</div>
            <div className="mt-1 text-xs text-white/40">{label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">
        <ShieldCheck className="mr-2 inline h-3.5 w-3.5" />
        {message}
      </div>

      <div className="space-y-4">
        {items.map((item, index) => (
          <motion.section
            key={item.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            className="glass-card p-5"
          >
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">
                  v{item.version}
                </h2>
                <p className="mt-1 text-xs text-white/40">
                  {item.environment} · requested by {item.requestedBy} ·{" "}
                  {item.createdAt}
                </p>
              </div>
              <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-white/65">
                {item.status}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-3">
              {item.gates.map((gate) => (
                <div
                  key={gate.id}
                  className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-white">
                        {gate.name}
                      </div>
                      <div className="mt-1 text-xs text-white/30">
                        {gate.updatedAt}
                      </div>
                    </div>
                    <span
                      className={`rounded-full border px-2.5 py-1 text-[11px] ${statusClass[gate.status]}`}
                    >
                      {gate.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={() => void act(item.id, "approve")}
                className="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300"
              >
                <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
                Approve release
              </button>
              <button
                onClick={() => void act(item.id, "reject")}
                className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300"
              >
                <CircleAlert className="mr-1 inline h-3.5 w-3.5" />
                Reject
              </button>
              <button
                onClick={() => void act(item.id, "rollback")}
                className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300"
              >
                <Undo2 className="mr-1 inline h-3.5 w-3.5" />
                Rollback
              </button>
            </div>
          </motion.section>
        ))}
      </div>
    </div>
  );
}
