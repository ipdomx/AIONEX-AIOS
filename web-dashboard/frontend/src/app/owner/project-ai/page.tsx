"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  CheckCircle2,
  CircleDollarSign,
  RefreshCw,
  Save,
  ShieldCheck,
  UserCog,
  Users,
} from "lucide-react";

import {
  clearProjectAIUserPolicy,
  fetchProjectAIAccess,
  fetchProjectAIProviderFinance,
  refreshProjectAIModelEvidence,
  updateProjectAIPlanPolicy,
  updateProjectAIProviderFinance,
  updateProjectAIUserPolicy,
  type ProjectAIAccessClass,
  type ProjectAIAccessPolicy,
  type ProjectAIAccessSnapshot,
  type ProjectAIProviderFinance,
} from "@/lib/owner-project-ai";

const emptySnapshot: ProjectAIAccessSnapshot = {
  platform_provider_organization_id: "",
  plan_policies: {
    free: {
      enabled: true,
      access_class: "free",
      allowed_provider_models: [],
      max_project_cost_usd: 0,
      offline_only: true,
      privacy_mode: true,
      max_fallbacks: 0,
    },
    paid: {
      enabled: true,
      access_class: "paid",
      allowed_provider_models: [],
      max_project_cost_usd: 1,
      offline_only: false,
      privacy_mode: false,
      max_fallbacks: 1,
    },
  },
  user_overrides: [],
  users: [],
  providers: [],
};

type FinanceDraft = {
  funded_credit_usd: number;
  low_balance_threshold_usd: number;
  critical_balance_threshold_usd: number;
  enabled: boolean;
};

function modelKey(provider: string, model: string) {
  return `${provider}:${model}`;
}

function toggleModel(policy: ProjectAIAccessPolicy, key: string) {
  const current = new Set(policy.allowed_provider_models);
  if (current.has(key)) current.delete(key);
  else current.add(key);
  return { ...policy, allowed_provider_models: [...current].sort() };
}

export default function OwnerProjectAIPage() {
  const [snapshot, setSnapshot] =
    useState<ProjectAIAccessSnapshot>(emptySnapshot);
  const [drafts, setDrafts] = useState(emptySnapshot.plan_policies);
  const [finance, setFinance] = useState<
    Record<string, ProjectAIProviderFinance | null>
  >({});
  const [financeDrafts, setFinanceDrafts] = useState<
    Record<string, FinanceDraft>
  >({});
  const [selectedUserId, setSelectedUserId] = useState("");
  const [userClass, setUserClass] = useState<ProjectAIAccessClass>("paid");
  const [userModels, setUserModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [message, setMessage] = useState(
    "Synchronizing Project AI launch policy...",
  );

  const modelOptions = useMemo(
    () =>
      snapshot.providers.flatMap((provider) =>
        provider.validated_models.map((model) => ({
          key: modelKey(provider.type, model.model),
          providerId: provider.id,
          provider: provider.type,
          model: model.model,
          local: model.local,
          expiresAt: model.expires_at,
        })),
      ),
    [snapshot.providers],
  );

  const freeOptions = modelOptions.filter(
    (item) => item.local && item.provider === "ollama",
  );
  const paidOptions = modelOptions.filter(
    (item) => !item.local || item.provider !== "ollama",
  );

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const next = await fetchProjectAIAccess(signal);
      setSnapshot(next);
      setDrafts(next.plan_policies);
      if (!selectedUserId && next.users[0]) setSelectedUserId(next.users[0].id);

      const rows = await Promise.all(
        next.providers.map(async (provider) => {
          try {
            return [
              provider.id,
              await fetchProjectAIProviderFinance(provider.id, signal),
            ] as const;
          } catch {
            return [provider.id, null] as const;
          }
        }),
      );
      const nextFinance = Object.fromEntries(rows) as Record<
        string,
        ProjectAIProviderFinance | null
      >;
      setFinance(nextFinance);
      setFinanceDrafts(
        Object.fromEntries(
          next.providers.map((provider) => {
            const row = nextFinance[provider.id];
            return [
              provider.id,
              {
                funded_credit_usd: row?.funded_usd ?? 0,
                low_balance_threshold_usd: row?.low_balance_threshold_usd ?? 5,
                critical_balance_threshold_usd:
                  row?.critical_balance_threshold_usd ?? 2,
                enabled: row?.enabled ?? true,
              },
            ];
          }),
        ),
      );
      setMessage("Project AI launch policy synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage("Project AI launch policy synchronization failed.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedUser = snapshot.users.find(
    (user) => user.id === selectedUserId,
  );
  const selectedOverride = snapshot.user_overrides.find(
    (item) => item.user_id === selectedUserId,
  );

  useEffect(() => {
    if (!selectedUser) return;
    const policy =
      selectedOverride?.policy ??
      snapshot.plan_policies[selectedUser.access_class];
    setUserClass(policy.access_class);
    setUserModels(policy.allowed_provider_models);
  }, [selectedUserId, selectedUser, selectedOverride, snapshot.plan_policies]);

  async function savePlan(accessClass: ProjectAIAccessClass) {
    setSaving(`plan:${accessClass}`);
    try {
      await updateProjectAIPlanPolicy(accessClass, drafts[accessClass]);
      setMessage(
        `${accessClass === "free" ? "Free" : "Paid"} Project AI policy saved.`,
      );
      await load();
    } catch {
      setMessage("Project AI plan policy update failed.");
    } finally {
      setSaving(null);
    }
  }

  async function saveUserOverride() {
    if (!selectedUserId) return;
    setSaving(`user:${selectedUserId}`);
    try {
      const base = drafts[userClass];
      await updateProjectAIUserPolicy(selectedUserId, {
        ...base,
        access_class: userClass,
        allowed_provider_models: userModels,
      });
      setMessage("User Project AI override saved.");
      await load();
    } catch {
      setMessage("User Project AI override update failed.");
    } finally {
      setSaving(null);
    }
  }

  async function clearUserOverride() {
    if (!selectedUserId) return;
    setSaving(`user:${selectedUserId}`);
    try {
      await clearProjectAIUserPolicy(selectedUserId);
      setMessage("User override cleared; plan default restored.");
      await load();
    } catch {
      setMessage("User override could not be cleared.");
    } finally {
      setSaving(null);
    }
  }

  async function refreshModelEvidence() {
    setSaving("models:refresh");
    try {
      const result = await refreshProjectAIModelEvidence();
      setMessage(
        `Model evidence refreshed: ${result.validated.length} validated, ${result.unavailable.length} unavailable, ${result.probe_failures.length} probe failures.`,
      );
      await load();
    } catch {
      setMessage(
        "Model evidence refresh failed; existing unexpired evidence was not replaced by a transient failure.",
      );
    } finally {
      setSaving(null);
    }
  }

  async function saveFinance(providerId: string) {
    const draft = financeDrafts[providerId];
    if (!draft) return;
    setSaving(`finance:${providerId}`);
    try {
      await updateProjectAIProviderFinance(providerId, draft);
      setMessage("Provider credit policy saved and monitoring baseline reset.");
      await load();
    } catch {
      setMessage("Provider credit policy update failed.");
    } finally {
      setSaving(null);
    }
  }

  function policyPanel(accessClass: ProjectAIAccessClass) {
    const policy = drafts[accessClass];
    const options = accessClass === "free" ? freeOptions : paidOptions;
    const pending = policy.allowed_provider_models.filter(
      (key) =>
        !modelOptions.some(
          (item) => item.key.toLowerCase() === key.toLowerCase(),
        ),
    );
    return (
      <section className="glass-card p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              {accessClass === "free" ? (
                <ShieldCheck className="h-4 w-4" />
              ) : (
                <Bot className="h-4 w-4" />
              )}
              {accessClass === "free" ? "Free users" : "Paid users"}
            </div>
            <p className="mt-2 text-xs leading-relaxed text-white/45">
              {accessClass === "free"
                ? "Local/free providers only. External provider spend stays blocked."
                : "Only Owner-approved models with current validated evidence can route."}
            </p>
          </div>
          <button
            className="btn-primary"
            disabled={saving !== null}
            onClick={() => void savePlan(accessClass)}
          >
            <Save className="h-4 w-4" /> Save
          </button>
        </div>
        <div className="mt-4 grid gap-2">
          {options.length === 0 ? (
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-xs text-white/45">
              No validated {accessClass} model is available yet. Routing remains
              fail-closed.
            </div>
          ) : (
            options.map((item) => (
              <label
                key={item.key}
                className="flex items-center gap-3 rounded-xl border border-white/[0.06] p-3 text-xs text-white/70"
              >
                <input
                  type="checkbox"
                  checked={policy.allowed_provider_models.some(
                    (key) => key.toLowerCase() === item.key.toLowerCase(),
                  )}
                  onChange={() =>
                    setDrafts((current) => ({
                      ...current,
                      [accessClass]: toggleModel(
                        current[accessClass],
                        item.key,
                      ),
                    }))
                  }
                />
                <span className="min-w-0 flex-1 truncate">
                  {item.provider} · {item.model}
                </span>
                <span className="text-white/35">
                  {item.local ? "local" : "provider"}
                </span>
              </label>
            ))
          )}
        </div>
        {pending.length > 0 && (
          <div className="mt-3 rounded-xl border border-orange-500/20 bg-orange-500/10 p-3 text-xs text-orange-200">
            Awaiting fresh provider evidence: {pending.join(", ")}
          </div>
        )}
        <label className="mt-4 block text-xs text-white/45">
          Maximum project provider cost (USD)
          <input
            className="mt-2 w-full rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2 text-white"
            type="number"
            min={0}
            step="0.01"
            disabled={accessClass === "free"}
            value={policy.max_project_cost_usd}
            onChange={(event) =>
              setDrafts((current) => ({
                ...current,
                [accessClass]: {
                  ...current[accessClass],
                  max_project_cost_usd: Number(event.target.value),
                },
              }))
            }
          />
        </label>
      </section>
    );
  }

  return (
    <div className="min-w-0 space-y-6">
      <header className="glass-card p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
              <UserCog className="h-3.5 w-3.5" /> Project AI Launch Control
            </div>
            <h1 className="mt-3 text-3xl font-bold text-white">
              100-user launch routing
            </h1>
            <p className="mt-2 max-w-4xl text-sm leading-relaxed text-white/45">
              Control Free/Paid provider access, user overrides, validated
              models, and provider credit alerts without exposing provider
              credentials.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded-xl border border-white/[0.08] px-4 py-2.5 text-xs text-white/70"
              disabled={loading || saving !== null}
              onClick={() => void load()}
            >
              <RefreshCw
                className={`mr-2 inline h-4 w-4 ${loading ? "animate-spin" : ""}`}
              />
              Refresh
            </button>
            <button
              className="btn-primary"
              disabled={loading || saving !== null}
              onClick={() => void refreshModelEvidence()}
            >
              <RefreshCw
                className={`h-4 w-4 ${saving === "models:refresh" ? "animate-spin" : ""}`}
              />
              Refresh model evidence
            </button>
          </div>
        </div>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="glass-card p-4">
          <Users className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">100</div>
          <div className="text-xs text-white/40">Launch admission target</div>
        </div>
        <div className="glass-card p-4">
          <Bot className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {snapshot.providers.length}
          </div>
          <div className="text-xs text-white/40">Platform providers</div>
        </div>
        <div className="glass-card p-4">
          <CheckCircle2 className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {modelOptions.length}
          </div>
          <div className="text-xs text-white/40">Validated models</div>
        </div>
        <div className="glass-card p-4">
          <CircleDollarSign className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {Object.values(finance).filter(Boolean).length}
          </div>
          <div className="text-xs text-white/40">
            Credit monitors configured
          </div>
        </div>
      </section>

      <div className="rounded-xl border border-electric-500/15 bg-electric-500/5 px-4 py-3 text-xs text-electric-200/80">
        {message}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {policyPanel("free")}
        {policyPanel("paid")}
      </div>

      <section className="glass-card p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <Users className="h-4 w-4" /> User override
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-3">
          <label className="text-xs text-white/45">
            User
            <select
              className="mt-2 w-full rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2 text-white"
              value={selectedUserId}
              onChange={(event) => setSelectedUserId(event.target.value)}
            >
              {snapshot.users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.email} · {user.plan}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-white/45">
            Access class
            <select
              className="mt-2 w-full rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2 text-white"
              value={userClass}
              onChange={(event) => {
                const next = event.target.value as ProjectAIAccessClass;
                setUserClass(next);
                setUserModels(drafts[next].allowed_provider_models);
              }}
            >
              <option value="free">Free</option>
              <option value="paid">Paid</option>
            </select>
          </label>
          <div className="flex items-end gap-2">
            <button
              className="btn-primary flex-1"
              disabled={!selectedUserId || saving !== null}
              onClick={() => void saveUserOverride()}
            >
              <Save className="h-4 w-4" /> Save override
            </button>
            <button
              className="rounded-xl border border-white/[0.08] px-4 py-2.5 text-xs text-white/60"
              disabled={!selectedUserId || saving !== null}
              onClick={() => void clearUserOverride()}
            >
              Use plan default
            </button>
          </div>
        </div>
        {selectedUser && (
          <div className="mt-3 text-xs text-white/40">
            {selectedUser.name} · {selectedUser.organization_name} ·{" "}
            {selectedUser.override_active
              ? "Owner override active"
              : "Plan default"}
          </div>
        )}
        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {(userClass === "free" ? freeOptions : paidOptions).map((item) => (
            <label
              key={item.key}
              className="flex items-center gap-3 rounded-xl border border-white/[0.06] p-3 text-xs text-white/70"
            >
              <input
                type="checkbox"
                checked={userModels.some(
                  (key) => key.toLowerCase() === item.key.toLowerCase(),
                )}
                onChange={() =>
                  setUserModels((current) =>
                    current.some(
                      (key) => key.toLowerCase() === item.key.toLowerCase(),
                    )
                      ? current.filter(
                          (key) => key.toLowerCase() !== item.key.toLowerCase(),
                        )
                      : [...current, item.key].sort(),
                  )
                }
              />
              <span className="truncate">
                {item.provider} · {item.model}
              </span>
            </label>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-white">
            Provider credit monitoring
          </h2>
          <p className="mt-1 text-xs text-white/40">
            Record funded credit and alert thresholds. Actual Project-AI spend
            is deducted from the recorded baseline.
          </p>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          {snapshot.providers.map((provider) => {
            const row = finance[provider.id];
            const draft = financeDrafts[provider.id];
            if (!draft) return null;
            return (
              <div key={provider.id} className="glass-card p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-white">
                      {provider.type}
                    </div>
                    <div className="mt-1 text-xs text-white/40">
                      {provider.validated_models.length} validated models ·{" "}
                      {row?.state ?? "not configured"}
                    </div>
                  </div>
                  {row && (
                    <div className="text-right">
                      <div className="text-lg font-bold text-white">
                        ${row.remaining_usd.toFixed(2)}
                      </div>
                      <div className="text-[11px] text-white/35">
                        estimated remaining
                      </div>
                    </div>
                  )}
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2">
                  {(
                    [
                      ["funded_credit_usd", "Funded"],
                      ["low_balance_threshold_usd", "Low"],
                      ["critical_balance_threshold_usd", "Critical"],
                    ] as const
                  ).map(([key, label]) => (
                    <label key={key} className="text-[11px] text-white/40">
                      {label}
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        className="mt-1 w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-2 text-xs text-white"
                        value={draft[key]}
                        onChange={(event) =>
                          setFinanceDrafts((current) => ({
                            ...current,
                            [provider.id]: {
                              ...current[provider.id],
                              [key]: Number(event.target.value),
                            },
                          }))
                        }
                      />
                    </label>
                  ))}
                </div>
                <button
                  className="btn-primary mt-4 w-full justify-center"
                  disabled={saving !== null}
                  onClick={() => void saveFinance(provider.id)}
                >
                  <Save className="h-4 w-4" /> Save credit policy
                </button>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
