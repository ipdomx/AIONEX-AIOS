"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
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
  fetchProjectExecutionFabric,
  runProductionRuntimeCommand,
  type ProjectExecutionFabricSnapshot,
  type ProductionRuntimeAction,
  type ProductionRuntimeSnapshot,
  type ProductionRuntimeTarget,
} from "@/lib/owner-production-runtime";

const emptySnapshot: ProductionRuntimeSnapshot = {
  generated_at: "",
  completion: 0,
  public_origin: "",
  api_origin: "",
  targets: [],
};

const emptyFabric: ProjectExecutionFabricSnapshot = {
  captured_at: "",
  queued: 0,
  running: 0,
  retry_queued: 0,
  dead_lettered: 0,
  oldest_queue_wait_seconds: 0,
  queue_by_resource_class: {},
  workers_online: 0,
  worker_capacity: 0,
  worker_active_slots: 0,
  worker_saturation: 0,
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
  const [fabric, setFabric] =
    useState<ProjectExecutionFabricSnapshot>(emptyFabric);
  const [loading, setLoading] = useState(true);
  const [actingTarget, setActingTarget] = useState<string | null>(null);
  const [message, setMessage] = useState("Validating production runtime...");
  const actionInFlight = useRef(false);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchProductionRuntime(signal);
      if (signal?.aborted) return;
      setSnapshot(data);

      try {
        const fabricData = await fetchProjectExecutionFabric(signal);
        if (signal?.aborted) return;
        setFabric(fabricData);
        setMessage(
          "Production runtime and project execution fabric synchronized.",
        );
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setFabric(emptyFabric);
        setMessage(
          "Production runtime synchronized; project execution fabric is temporarily unavailable.",
        );
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setSnapshot(emptySnapshot);
        setFabric(emptyFabric);
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
    if (actionInFlight.current) return;
    actionInFlight.current = true;
    setActingTarget(targetId);
    setMessage(`Running ${action} for ${targetId}...`);
    try {
      const data = await runProductionRuntimeCommand(targetId, action);
      setSnapshot(data);
      setMessage(
        `Live backend dependency ${action} completed and the snapshot was refreshed.`,
      );
    } catch {
      setMessage("Production runtime command failed.");
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
            <Globe2 className="h-3.5 w-3.5" /> Production Runtime
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Backend Dependency Readiness
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Live health evidence for the backend dependencies exposed by the
            production runtime contract.
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
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-white/30">
              Live dependency readiness
            </div>
            <div className="mt-2 text-4xl font-bold text-white">
              {snapshot.completion}%
            </div>
          </div>
          <div className="text-xs text-white/50">
            <div>Public origin: {snapshot.public_origin || "Not loaded"}</div>
            <div className="mt-1">
              API origin: {snapshot.api_origin || "Not loaded"}
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

      <div className="glass-card p-5">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-sm font-semibold text-white">
              Distributed project execution fabric
            </div>
            <div className="mt-1 text-xs text-white/40">
              PostgreSQL durable queue, worker membership, retries and
              saturation.
            </div>
          </div>
          <div className="text-xs text-white/40">
            {fabric.captured_at || "Not loaded"}
          </div>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {[
            ["Queued", fabric.queued],
            ["Running", fabric.running],
            ["Retry queued", fabric.retry_queued],
            ["Dead-letter", fabric.dead_lettered],
            ["Workers", fabric.workers_online],
            ["Saturation", `${Math.round(fabric.worker_saturation * 100)}%`],
          ].map(([label, value]) => (
            <div
              key={String(label)}
              className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3"
            >
              <div className="text-lg font-semibold text-white">{value}</div>
              <div className="mt-1 text-[11px] text-white/35">{label}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-white/40">
          <span>Capacity: {fabric.worker_capacity}</span>
          <span>Active slots: {fabric.worker_active_slots}</span>
          <span>
            Oldest wait: {Math.round(fabric.oldest_queue_wait_seconds)}s
          </span>
          <span>
            Queues:{" "}
            {Object.entries(fabric.queue_by_resource_class)
              .map(([name, count]) => `${name}=${count}`)
              .join(", ") || "empty"}
          </span>
        </div>
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
              <Link
                href="/owner/release-governance"
                className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300"
              >
                Open release pipeline
              </Link>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
