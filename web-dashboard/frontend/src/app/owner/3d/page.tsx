"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  Box,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  cleanupOwnerThreeD,
  fetchOwnerThreeD,
  resetOwnerThreeDCircuit,
  updateOwnerThreeD,
  type OwnerThreeDOperations,
  type OwnerThreeDPolicy,
} from "@/lib/owner-three-d";

export default function OwnerThreeDPage() {
  const [policy, setPolicy] = useState<OwnerThreeDPolicy | null>(null);
  const [operations, setOperations] = useState<OwnerThreeDOperations | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading owner 3D policy…");
  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const result = await fetchOwnerThreeD(signal);
      setPolicy(result.policy);
      setOperations(result.operations);
      setMessage("3D access and GPU limits synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setMessage("3D policy could not be loaded.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    const c = new AbortController();
    void load(c.signal);
    return () => c.abort();
  }, []);
  function set<K extends keyof OwnerThreeDPolicy>(
    key: K,
    value: OwnerThreeDPolicy[K],
  ) {
    setPolicy((current) => (current ? { ...current, [key]: value } : current));
  }
  async function save() {
    if (!policy) return;
    setBusy(true);
    try {
      const result = await updateOwnerThreeD(policy);
      setPolicy(result.policy);
      setOperations(result.operations);
      setMessage("Owner 3D policy saved and audit-logged.");
    } catch {
      setMessage("3D policy update failed.");
    } finally {
      setBusy(false);
    }
  }

  async function resetCircuit() {
    setBusy(true);
    try {
      const result = await resetOwnerThreeDCircuit();
      setPolicy(result.policy);
      setOperations(result.operations);
      setMessage("3D provider circuit reset and audit-logged.");
    } catch {
      setMessage("3D provider circuit reset failed.");
    } finally {
      setBusy(false);
    }
  }

  async function cleanup() {
    setBusy(true);
    try {
      const result = await cleanupOwnerThreeD();
      setPolicy(result.policy);
      setOperations(result.operations);
      setMessage(
        `3D cleanup complete: ${result.cleanup_result?.artifacts_expired ?? 0} artifacts expired, ${result.cleanup_result?.stale_inputs_cleaned ?? 0} stale inputs cleaned.`,
      );
    } catch {
      setMessage("3D cleanup failed.");
    } finally {
      setBusy(false);
    }
  }
  if (!policy)
    return (
      <div className="glass-card p-6 text-sm text-white/50">{message}</div>
    );
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <Box className="h-3.5 w-3.5" /> Owner 3D Control
          </div>
          <h1 className="text-3xl font-bold text-white">
            3D Access, Spend & Recovery
          </h1>
          <p className="mt-2 max-w-4xl text-sm text-white/45">
            The highest public tier is the default eligibility boundary. The
            Super Owner can enable or suspend 3D, change eligible plans, grant
            or deny individual users, and set every GPU cost/recovery limit.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            className="btn-secondary"
            disabled={loading || busy}
            onClick={() => void load()}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <button
            className="btn-primary"
            disabled={busy}
            onClick={() => void save()}
          >
            <Save className="h-4 w-4" />
            Save policy
          </button>
        </div>
      </div>
      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>
      {operations && (
        <section className="glass-card space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-white">
              <Activity className="h-5 w-5 text-cyan-300" />
              <span className="font-semibold">3D Operations & Resilience</span>
            </div>
            <div className="flex gap-2">
              <button
                className="btn-secondary"
                disabled={busy}
                onClick={() => void resetCircuit()}
              >
                <RotateCcw className="h-4 w-4" /> Reset provider circuit
              </button>
              <button
                className="btn-secondary"
                disabled={busy}
                onClick={() => void cleanup()}
              >
                <Trash2 className="h-4 w-4" /> Run cleanup
              </button>
            </div>
          </div>
          <div className="grid gap-3 text-xs md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl bg-black/20 p-3 text-white/60">
              Circuit{" "}
              <b className="ml-2 text-white">{operations.circuit.state}</b>
              <div className="mt-1 text-white/35">
                Failures: {operations.circuit.consecutive_failures}
              </div>
            </div>
            <div className="rounded-xl bg-black/20 p-3 text-white/60">
              Success rate{" "}
              <b className="ml-2 text-white">
                {operations.jobs.success_rate_pct}%
              </b>
              <div className="mt-1 text-white/35">
                {operations.jobs.completed} completed / {operations.jobs.failed}{" "}
                failed
              </div>
            </div>
            <div className="rounded-xl bg-black/20 p-3 text-white/60">
              GPU runtime{" "}
              <b className="ml-2 text-white">
                {operations.jobs.avg_gpu_runtime_seconds}s
              </b>
              <div className="mt-1 text-white/35">
                Cold start: {operations.jobs.avg_provider_delay_seconds}s
              </div>
            </div>
            <div className="rounded-xl bg-black/20 p-3 text-white/60">
              Spend{" "}
              <b className="ml-2 text-white">
                ${operations.spend.daily_usd.toFixed(4)}
              </b>
              <div className="mt-1 text-white/35">
                Month: ${operations.spend.monthly_usd.toFixed(4)}
              </div>
            </div>
          </div>
        </section>
      )}
      <section className="glass-card p-5 space-y-4">
        <div className="flex items-center gap-2 text-white">
          <ShieldCheck className="h-5 w-5 text-green-300" />
          <span className="font-semibold">User eligibility</span>
        </div>
        <label className="flex items-center justify-between text-sm text-white/70">
          <span>3D service enabled</span>
          <input
            type="checkbox"
            checked={policy.enabled}
            onChange={(e) => set("enabled", e.target.checked)}
          />
        </label>
        <label className="block text-xs text-white/45">
          Eligible plan codes
          <input
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
            value={policy.allowed_plan_codes.join(", ")}
            onChange={(e) =>
              set(
                "allowed_plan_codes",
                e.target.value
                  .split(",")
                  .map((v) => v.trim())
                  .filter(Boolean),
              )
            }
          />
        </label>
        <label className="block text-xs text-white/45">
          Required entitlement
          <input
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
            value={policy.required_entitlement}
            onChange={(e) => set("required_entitlement", e.target.value)}
          />
        </label>
        <label className="block text-xs text-white/45">
          Explicitly allowed user IDs
          <input
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
            value={policy.allowed_user_ids.join(", ")}
            onChange={(e) =>
              set(
                "allowed_user_ids",
                e.target.value
                  .split(",")
                  .map((v) => v.trim())
                  .filter(Boolean),
              )
            }
          />
        </label>
        <label className="block text-xs text-white/45">
          Explicitly denied user IDs
          <input
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
            value={policy.denied_user_ids.join(", ")}
            onChange={(e) =>
              set(
                "denied_user_ids",
                e.target.value
                  .split(",")
                  .map((v) => v.trim())
                  .filter(Boolean),
              )
            }
          />
        </label>
      </section>
      <section className="glass-card p-5 space-y-3">
        <label className="block text-xs text-white/45">
          GLB compression policy
          <select
            className="mt-2 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
            value={policy.compression_policy}
            onChange={(e) =>
              set("compression_policy", e.target.value as "compat" | "meshopt")
            }
          >
            <option value="compat" className="bg-ink-900">
              Compatibility
            </option>
            <option value="meshopt" className="bg-ink-900">
              Meshopt
            </option>
          </select>
        </label>
        <p className="text-xs leading-5 text-white/35">
          Generation quota, image size, texture resolution, artifact retention
          and signed-link lifetime below are enforced server-side for every
          user.
        </p>
      </section>
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(
          [
            ["max_concurrent_jobs_per_user", "Concurrent jobs / user", 1],
            ["max_runtime_seconds", "Max runtime seconds", 60],
            ["max_queue_seconds", "Max queue seconds", 10],
            ["max_retries", "Max retries", 0],
            ["max_estimated_job_cost_usd", "Max job cost USD", 0.01],
            ["daily_spend_limit_usd", "Daily spend ceiling USD", 0.01],
            ["monthly_spend_limit_usd", "Monthly spend ceiling USD", 0.01],
            ["owner_alert_threshold_pct", "Owner alert threshold %", 1],
            ["monthly_jobs_per_user", "Monthly jobs / user", 1],
            ["max_input_megabytes", "Max input image MB", 1],
            ["max_texture_size", "Max texture size", 512],
            ["artifact_retention_days", "Artifact retention days", 1],
            ["signed_url_ttl_seconds", "Signed URL lifetime seconds", 60],
            [
              "duplicate_window_seconds",
              "Duplicate protection window seconds",
              30,
            ],
            ["provider_failure_threshold", "Provider failure threshold", 1],
            [
              "provider_circuit_open_seconds",
              "Provider circuit open seconds",
              30,
            ],
            ["cleanup_interval_seconds", "Cleanup interval seconds", 30],
            ["cleanup_batch_size", "Cleanup batch size", 1],
            [
              "temporary_input_retention_hours",
              "Temporary input retention hours",
              1,
            ],
          ] as const
        ).map(([key, label, min]) => (
          <label key={key} className="glass-card p-4 text-xs text-white/45">
            {label}
            <input
              type="number"
              min={min}
              className="mt-2 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
              value={policy[key]}
              onChange={(e) => set(key, Number(e.target.value) as never)}
            />
          </label>
        ))}
      </section>
    </div>
  );
}
