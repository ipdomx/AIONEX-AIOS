"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import {
  fetchFinalPlatformIntegration,
  runFinalPlatformIntegrationCommand,
  type FinalIntegrationAction,
  type FinalIntegrationSnapshot,
  type FinalIntegrationTarget,
} from "@/lib/owner-final-platform-integration";

const emptySnapshot: FinalIntegrationSnapshot = {
  generated_at: "",
  completion: 0,
  closed: false,
  targets: [],
};

const statusClass: Record<FinalIntegrationTarget["status"], string> = {
  ready: "border-green-500/20 bg-green-500/10 text-green-300",
  warning: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  blocked: "border-red-500/20 bg-red-500/10 text-red-300",
};

export default function FinalPlatformIntegrationPage() {
  const [snapshot, setSnapshot] =
    useState<FinalIntegrationSnapshot>(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [actingTarget, setActingTarget] = useState<string | null>(null);
  const [message, setMessage] = useState(
    "Running final platform integration checks...",
  );
  const actionInFlight = useRef(false);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchFinalPlatformIntegration(signal);
      setSnapshot(data);
      setMessage("Final platform integration synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage("Final platform integration synchronization failed.");
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
      warning: snapshot.targets.filter((item) => item.status === "warning")
        .length,
      blocked: snapshot.targets.filter((item) => item.status === "blocked")
        .length,
    }),
    [snapshot.targets],
  );

  async function command(targetId: string, action: FinalIntegrationAction) {
    if (actionInFlight.current) return;
    if (
      action === "close" &&
      !window.confirm(
        "Record release approval from the current live dependency and non-owner gate evidence?",
      )
    ) {
      return;
    }
    actionInFlight.current = true;
    setActingTarget(targetId);
    setMessage(`Running ${action} for ${targetId}...`);
    try {
      const data = await runFinalPlatformIntegrationCommand(targetId, action);
      setSnapshot(
        action === "close" ? { ...data, closed: data.closed ?? true } : data,
      );
      setMessage(
        action === "close"
          ? "The release approval was recorded from the current live dependency and gate evidence."
          : "Live dependency and release-gate validation completed.",
      );
    } catch {
      setMessage("Final integration command failed.");
    } finally {
      actionInFlight.current = false;
      setActingTarget(null);
    }
  }

  const summaryCards: Array<{
    label: string;
    value: number;
    Icon: typeof CheckCircle2;
  }> = [
    { label: "Ready", value: summary.ready, Icon: CheckCircle2 },
    { label: "Warnings", value: summary.warning, Icon: TriangleAlert },
    { label: "Blocked", value: summary.blocked, Icon: XCircle },
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
            <ShieldCheck className="h-3.5 w-3.5" /> Final Owner Integration
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Live Dependencies & Release Approval
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Owner review of live backend dependency health and non-owner release
            gates before recording release approval.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            disabled={loading || actingTarget !== null}
            onClick={() => void load()}
            className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Run checks
          </button>
          <button
            disabled={
              loading ||
              actingTarget !== null ||
              snapshot.completion !== 100 ||
              snapshot.closed === true
            }
            onClick={() => void command("platform", "close")}
            className="rounded-xl border border-green-500/20 bg-green-500/10 px-4 py-2 text-xs text-green-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {snapshot.closed
              ? "Release approval recorded"
              : "Record release approval"}
          </button>
        </div>
      </motion.div>

      <div className="glass-card p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wider text-white/30">
              Dependency and gate readiness
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
                disabled={loading || actingTarget !== null}
                onClick={() => void command(item.id, "validate")}
                className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/70 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {actingTarget === item.id ? "Validating…" : "Validate"}
              </button>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
