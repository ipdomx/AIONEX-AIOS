"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  CheckCircle2,
  CircleAlert,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  fetchOwnerFinalizationSnapshot,
  type OwnerFinalizationSnapshot,
} from "@/lib/owner-finalization";

const emptySnapshot: OwnerFinalizationSnapshot = {
  generatedAt: "",
  completion: 0,
  checks: [],
};

const statusClass: Record<"passed" | "warning" | "failed", string> = {
  passed: "border-green-500/20 bg-green-500/10 text-green-300",
  warning: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  failed: "border-red-500/20 bg-red-500/10 text-red-300",
};

type SummaryCard = {
  label: string;
  value: number;
  icon: LucideIcon;
};

export default function OwnerFinalizationPage() {
  const [snapshot, setSnapshot] =
    useState<OwnerFinalizationSnapshot>(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(
    "Running owner dashboard finalization checks...",
  );

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchOwnerFinalizationSnapshot(signal);
      setSnapshot(data);
      setMessage(
        `Finalization synchronized at ${new Date(data.generatedAt).toLocaleTimeString()}.`,
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setSnapshot(emptySnapshot);
        setMessage("Finalization backend contract is not available.");
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
      passed: snapshot.checks.filter((item) => item.status === "passed").length,
      warnings: snapshot.checks.filter((item) => item.status === "warning")
        .length,
      failed: snapshot.checks.filter((item) => item.status === "failed").length,
    }),
    [snapshot],
  );

  const summaryCards: SummaryCard[] = [
    { label: "Passed", value: summary.passed, icon: CheckCircle2 },
    { label: "Warnings", value: summary.warnings, icon: CircleAlert },
    { label: "Failed", value: summary.failed, icon: XCircle },
  ];

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <ShieldCheck className="h-3.5 w-3.5" /> Owner Dashboard Finalization
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Production Readiness & Closure
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Live dependency checks, unresolved critical-incident clearance,
            explicit performance telemetry, verified restore evidence, and Owner
            approval.
          </p>
        </div>
        <button
          disabled={loading}
          onClick={() => void load()}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Run checks
        </button>
      </motion.div>

      <div className="glass-card p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wider text-white/30">
              Overall completion
            </div>
            <div className="mt-2 text-4xl font-bold text-white">
              {snapshot.completion}%
            </div>
          </div>
          <div
            className={`rounded-full border px-4 py-2 text-sm ${snapshot.generatedAt ? "border-green-500/20 bg-green-500/10 text-green-300" : "border-white/10 bg-white/[0.04] text-white/45"}`}
          >
            {snapshot.generatedAt
              ? "Verified readiness result"
              : "Awaiting readiness data"}
          </div>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/[0.05]">
          <div
            className="h-full rounded-full bg-electric-400"
            style={{
              width: `${Math.min(100, Math.max(0, snapshot.completion))}%`,
            }}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {summaryCards.map(({ label, value, icon: Icon }) => (
          <div key={label} className="glass-card p-5">
            <Icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-3xl font-bold text-white">{value}</div>
            <div className="mt-1 text-xs text-white/40">{label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {snapshot.checks.map((item, index) => (
          <motion.div
            key={item.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            className="glass-card p-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold text-white">
                  {item.label}
                </h2>
                <p className="mt-1 text-xs text-white/40">
                  {item.category} · {item.details}
                </p>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[item.status]}`}
              >
                {item.status}
              </span>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
