"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import {
  Activity,
  CheckCircle2,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import {
  fetchOwnerOperationsIntegration,
  runOwnerOperationsCommand,
  type OperationsAction,
  type OperationsSnapshot,
  type OperationsTarget,
} from "@/lib/owner-operations-integration";

const emptySnapshot: OperationsSnapshot = {
  generated_at: "",
  completion: 0,
  targets: [],
};

const statusClass: Record<OperationsTarget["status"], string> = {
  healthy: "border-green-500/20 bg-green-500/10 text-green-300",
  degraded: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  offline: "border-red-500/20 bg-red-500/10 text-red-300",
};

export default function OwnerOperationsIntegrationPage() {
  const [snapshot, setSnapshot] = useState<OperationsSnapshot>(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [actingTarget, setActingTarget] = useState<string | null>(null);
  const [message, setMessage] = useState(
    "Synchronizing enterprise operations...",
  );
  const actionInFlight = useRef(false);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchOwnerOperationsIntegration(signal);
      setSnapshot(data);
      setMessage("Enterprise operations synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage("Operations synchronization failed.");
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
      healthy: snapshot.targets.filter((item) => item.status === "healthy")
        .length,
      degraded: snapshot.targets.filter((item) => item.status === "degraded")
        .length,
      offline: snapshot.targets.filter((item) => item.status === "offline")
        .length,
    }),
    [snapshot.targets],
  );

  const summaryCards = [
    { label: "Healthy", value: summary.healthy, Icon: CheckCircle2 },
    { label: "Degraded", value: summary.degraded, Icon: TriangleAlert },
    { label: "Offline", value: summary.offline, Icon: XCircle },
  ];

  async function command(targetId: string, action: OperationsAction) {
    if (actionInFlight.current) return;
    if (
      action === "recover" &&
      !window.confirm(`Request the governed recovery drill for ${targetId}?`)
    ) {
      return;
    }
    actionInFlight.current = true;
    setActingTarget(targetId);
    setMessage(`Running ${action} for ${targetId}...`);
    try {
      const data = await runOwnerOperationsCommand(targetId, action);
      setSnapshot(data);
      setMessage(
        action === "recover"
          ? "Restore drill queued. Track its durable worker status in the Recovery Center."
          : "Operations validation completed.",
      );
    } catch {
      setMessage("Operations command failed.");
    } finally {
      actionInFlight.current = false;
      setActingTarget(null);
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
            <Activity className="h-3.5 w-3.5" /> Owner Operations Integration
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Operational Dependencies & Recovery
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Live dependency health, alert state, and durable backup and recovery
            requests.
          </p>
        </div>
        <button
          disabled={loading || actingTarget !== null}
          onClick={() => void load()}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </motion.div>

      <div className="glass-card p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wider text-white/30">
              Operations readiness
            </div>
            <div className="mt-2 text-4xl font-bold text-white">
              {snapshot.completion}%
            </div>
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
        {summaryCards.map(({ label, value, Icon }) => (
          <div key={label} className="glass-card p-5">
            <Icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-3xl font-bold text-white">{value}</div>
            <div className="mt-1 text-xs text-white/40">{label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card flex items-center justify-between gap-4 p-4 text-xs text-electric-300">
        <span>{message}</span>
        <Link
          href="/owner/recovery"
          className="shrink-0 text-white/60 underline-offset-4 hover:underline"
        >
          Recovery Center
        </Link>
      </div>

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
                disabled={loading || actingTarget !== null}
                onClick={() => void command(item.id, "validate")}
                className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/70 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {actingTarget === item.id ? "Running…" : "Validate"}
              </button>
              {item.id === "backup" && (
                <button
                  disabled={loading || actingTarget !== null}
                  onClick={() => void command(item.id, "recover")}
                  className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <RotateCcw className="mr-1 inline h-3.5 w-3.5" />
                  Queue restore drill
                </button>
              )}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
