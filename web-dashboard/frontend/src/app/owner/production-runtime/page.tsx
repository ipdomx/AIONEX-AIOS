"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  Globe2,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import {
  fetchProductionRuntime,
  runProductionRuntimeCommand,
  type ProductionRuntimeAction,
  type ProductionRuntimeSnapshot,
  type ProductionRuntimeTarget,
} from "@/lib/owner-production-runtime";

const emptySnapshot: ProductionRuntimeSnapshot = {
  generated_at: "",
  completion: 0,
  public_origin: "https://ai.vip-e.net",
  api_origin: "https://api.ai.vip-e.net",
  targets: [],
};

const statusClass: Record<ProductionRuntimeTarget["status"], string> = {
  ready: "border-green-500/20 bg-green-500/10 text-green-300",
  degraded: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  blocked: "border-red-500/20 bg-red-500/10 text-red-300",
};

const summaryCards = [
  { key: "ready", label: "Ready", Icon: CheckCircle2 },
  { key: "degraded", label: "Degraded", Icon: TriangleAlert },
  { key: "blocked", label: "Blocked", Icon: XCircle },
] as const;

export default function OwnerProductionRuntimePage() {
  const [snapshot, setSnapshot] =
    useState<ProductionRuntimeSnapshot>(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Validating production runtime...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchProductionRuntime(signal);
      setSnapshot(data);
      setMessage("Production runtime synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage("Production runtime synchronization failed.");
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
      ready: snapshot.targets.filter((item) => item.status === "ready").length,
      degraded: snapshot.targets.filter((item) => item.status === "degraded")
        .length,
      blocked: snapshot.targets.filter((item) => item.status === "blocked")
        .length,
    }),
    [snapshot.targets],
  );

  async function command(targetId: string, action: ProductionRuntimeAction) {
    setMessage(`Running ${action} for ${targetId}...`);
    try {
      const data = await runProductionRuntimeCommand(targetId, action);
      setSnapshot(data);
      setMessage(
        `Production runtime ${action} request acknowledged; the current snapshot was refreshed.`,
      );
    } catch {
      setMessage("Production runtime command failed.");
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
            <Globe2 className="h-3.5 w-3.5" /> Production Runtime
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Deployment-Ready Runtime
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Final runtime preparation for ai.vip-e.net and environment-driven
            production deployment.
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

      <div className="glass-card p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-white/30">
              Production completion
            </div>
            <div className="mt-2 text-4xl font-bold text-white">
              {snapshot.completion}%
            </div>
          </div>
          <div className="text-xs text-white/50">
            <div>{snapshot.public_origin}</div>
            <div className="mt-1">{snapshot.api_origin}</div>
          </div>
          <ShieldCheck className="h-8 w-8 text-electric-300" />
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
        {summaryCards.map(({ key, label, Icon }) => (
          <div key={key} className="glass-card p-5">
            <Icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-3xl font-bold text-white">
              {summary[key]}
            </div>
            <div className="mt-1 text-xs text-white/40">{label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {snapshot.targets.map((item, index) => (
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
                  {item.name}
                </h2>
                <p className="mt-1 text-xs text-white/40">
                  {item.category} · Readiness {item.readiness}% ·{" "}
                  {item.last_checked_at}
                </p>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[item.status]}`}
              >
                {item.status}
              </span>
            </div>
            <p className="mt-4 text-xs leading-5 text-white/45">
              {item.details}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={() => void command(item.id, "validate")}
                className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/70"
              >
                Validate
              </button>
              <button
                onClick={() => void command(item.id, "prepare")}
                className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300"
              >
                Prepare
              </button>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
