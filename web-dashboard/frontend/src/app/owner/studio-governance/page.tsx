"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  RefreshCw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";

import {
  fetchOwnerStudioGovernance,
  updateOwnerStudioCapability,
  type OwnerStudioCapability,
  type OwnerStudioPolicy,
} from "@/lib/owner-studio-governance";

const planCodes = ["free", "starter", "professional", "enterprise"] as const;

function policyUpdate(policy: OwnerStudioPolicy) {
  return {
    enabled: policy.enabled,
    eligible_plans: policy.eligible_plans,
    daily_job_limit: policy.daily_job_limit,
    max_concurrent_jobs: policy.max_concurrent_jobs,
    max_attempts: policy.max_attempts,
    max_cost_usd: 0,
    provider_mode: "provider_neutral" as const,
    moderation_mode: policy.moderation_mode,
  };
}

export default function OwnerStudioGovernancePage() {
  const [items, setItems] = useState<OwnerStudioCapability[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("Loading Studio governance…");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const result = await fetchOwnerStudioGovernance(signal);
      setItems(result.capabilities);
      setMessage("Owner Studio policies synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setMessage("Owner Studio policies could not be loaded.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const enabledCount = useMemo(
    () => items.filter((item) => item.policy.enabled).length,
    [items],
  );

  function setPolicy<K extends keyof OwnerStudioPolicy>(
    capabilityId: string,
    key: K,
    value: OwnerStudioPolicy[K],
  ) {
    setItems((current) =>
      current.map((item) =>
        item.capability_id === capabilityId
          ? { ...item, policy: { ...item.policy, [key]: value } }
          : item,
      ),
    );
  }

  function togglePlan(capabilityId: string, plan: string, checked: boolean) {
    const current = items.find((item) => item.capability_id === capabilityId);
    if (!current) return;
    const plans = checked
      ? [...new Set([...current.policy.eligible_plans, plan])]
      : current.policy.eligible_plans.filter((item) => item !== plan);
    if (!plans.length) {
      setMessage("At least one eligible plan is required.");
      return;
    }
    setPolicy(capabilityId, "eligible_plans", plans);
  }

  async function save(item: OwnerStudioCapability) {
    setBusy(item.capability_id);
    try {
      const result = await updateOwnerStudioCapability(
        item.capability_id,
        policyUpdate(item.policy),
      );
      setItems((current) =>
        current.map((candidate) =>
          candidate.capability_id === item.capability_id
            ? {
                ...candidate,
                policy: result.policy,
                policy_source: "owner",
              }
            : candidate,
        ),
      );
      setMessage("Capability policy saved and audit-logged.");
    } catch {
      setMessage("Capability policy update failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <header className="glass-card p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex gap-3">
            <SlidersHorizontal className="mt-1 h-7 w-7 shrink-0 text-electric-300" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-electric-300">
                Unified Studio Capability Governance
              </p>
              <h1 className="mt-2 text-3xl font-bold text-white">
                Studio Governance
              </h1>
              <p className="mt-2 max-w-4xl text-sm leading-relaxed text-white/45">
                Control capability enablement, eligible plans, job quotas,
                concurrency, retry limits, and moderation without editing code
                or environment files. External provider activation remains
                separate and fail-closed.
              </p>
            </div>
          </div>
          <button
            type="button"
            className="btn-secondary"
            disabled={loading || busy !== null}
            onClick={() => void load()}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </header>

      <section className="grid gap-4 sm:grid-cols-3">
        <div className="glass-card p-5">
          <Sparkles className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-3xl font-bold text-white">
            {items.length}
          </div>
          <div className="mt-1 text-xs text-white/40">Capability families</div>
        </div>
        <div className="glass-card p-5">
          <ShieldCheck className="h-5 w-5 text-green-300" />
          <div className="mt-3 text-3xl font-bold text-white">
            {enabledCount}
          </div>
          <div className="mt-1 text-xs text-white/40">Enabled families</div>
        </div>
        <div className="glass-card p-5">
          <SlidersHorizontal className="h-5 w-5 text-violet-300" />
          <div className="mt-3 text-lg font-bold text-white">
            Provider-neutral
          </div>
          <div className="mt-1 text-xs text-white/40">Provider mode</div>
        </div>
      </section>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <section className="grid gap-4 xl:grid-cols-2">
        {items.map((item) => (
          <article
            key={item.capability_id}
            className="glass-card space-y-5 p-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold text-white">
                    {item.title}
                  </h2>
                  <span className="rounded-full border border-white/[0.08] px-2.5 py-1 text-[10px] text-white/40">
                    {item.policy_source === "owner"
                      ? "Owner override"
                      : "Default policy"}
                  </span>
                </div>
                <p className="mt-1 text-xs text-white/35">
                  Launch surface: {item.launch_surface} · Maturity:{" "}
                  {item.maturities.join(", ") || "specified"}
                </p>
              </div>
              <label className="flex items-center gap-2 text-xs text-white/55">
                Enabled
                <input
                  type="checkbox"
                  checked={item.policy.enabled}
                  onChange={(event) =>
                    setPolicy(
                      item.capability_id,
                      "enabled",
                      event.target.checked,
                    )
                  }
                />
              </label>
            </div>

            <div>
              <div className="text-xs font-medium text-white/60">
                Eligible plans
              </div>
              <div className="mt-2 flex flex-wrap gap-3">
                {planCodes.map((plan) => {
                  const supported = item.supported_plans.includes(plan);
                  return (
                    <label
                      key={plan}
                      className={`flex items-center gap-2 text-xs ${supported ? "text-white/45" : "text-white/20"}`}
                      title={
                        supported
                          ? undefined
                          : "This capability runtime does not support this plan."
                      }
                    >
                      <input
                        type="checkbox"
                        disabled={!supported}
                        checked={
                          supported && item.policy.eligible_plans.includes(plan)
                        }
                        onChange={(event) =>
                          togglePlan(
                            item.capability_id,
                            plan,
                            event.target.checked,
                          )
                        }
                      />
                      {plan}
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <label className="text-xs text-white/45">
                Daily job limit
                <input
                  type="number"
                  min={1}
                  max={10000}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
                  value={item.policy.daily_job_limit}
                  onChange={(event) =>
                    setPolicy(
                      item.capability_id,
                      "daily_job_limit",
                      Number(event.target.value),
                    )
                  }
                />
              </label>
              <label className="text-xs text-white/45">
                Max concurrent jobs
                <input
                  type="number"
                  min={1}
                  max={100}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
                  value={item.policy.max_concurrent_jobs}
                  onChange={(event) =>
                    setPolicy(
                      item.capability_id,
                      "max_concurrent_jobs",
                      Number(event.target.value),
                    )
                  }
                />
              </label>
              <label className="text-xs text-white/45">
                Max attempts
                <input
                  type="number"
                  min={1}
                  max={5}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
                  value={item.policy.max_attempts}
                  onChange={(event) =>
                    setPolicy(
                      item.capability_id,
                      "max_attempts",
                      Number(event.target.value),
                    )
                  }
                />
              </label>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs text-white/45">
                Moderation
                <select
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
                  value={item.policy.moderation_mode}
                  onChange={(event) =>
                    setPolicy(
                      item.capability_id,
                      "moderation_mode",
                      event.target
                        .value as OwnerStudioPolicy["moderation_mode"],
                    )
                  }
                >
                  <option value="standard">standard</option>
                  <option value="strict">strict</option>
                </select>
              </label>
              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3 text-xs text-white/45">
                <div>Provider mode: {item.policy.provider_mode}</div>
                <div className="mt-1">
                  External cost ceiling: ${item.policy.max_cost_usd.toFixed(2)}
                </div>
              </div>
            </div>

            {item.external_gates.length > 0 && (
              <div className="rounded-xl border border-orange-500/15 bg-orange-500/5 p-3 text-[11px] leading-5 text-orange-200/70">
                External gates: {item.external_gates.join(" · ")}
              </div>
            )}

            {(!item.runtime_launchable ||
              item.required_permissions.length > 0) && (
              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3 text-[11px] leading-5 text-white/40">
                {!item.runtime_launchable && (
                  <div>
                    Runtime launch: gated (
                    {item.activation_reason || "external activation required"})
                  </div>
                )}
                {item.required_permissions.length > 0 && (
                  <div>
                    Required user permissions:{" "}
                    {item.required_permissions.join(" · ")}
                  </div>
                )}
              </div>
            )}

            <button
              type="button"
              className="btn-primary"
              disabled={busy !== null}
              onClick={() => void save(item)}
            >
              <Save className="h-4 w-4" />
              Save policy
            </button>
          </article>
        ))}
      </section>
    </div>
  );
}
