"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDollarSign,
  FlaskConical,
  LockKeyhole,
  Plus,
  RefreshCw,
  Rocket,
  Save,
  ShieldCheck,
  Target,
  XCircle,
} from "lucide-react";

import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import { translateInterfaceText } from "@/lib/interface-translations";

import {
  armOwnerGrowthPilot,
  authorizeOwnerGrowthPilotLaunch,
  configureOwnerGrowthPilot,
  createOwnerGrowthPilot,
  disarmOwnerGrowthPilot,
  fetchOwnerGrowthMetaTargets,
  fetchOwnerGrowthPilotReadiness,
  fetchOwnerGrowthPilots,
  type GrowthControlledPilot,
  type GrowthMetaTargetDiscovery,
  type GrowthPilotReadiness,
  validateOwnerGrowthPilotReadOnly,
} from "@/lib/owner-growth-social";
import {
  fetchOwnerRuntimeSnapshot,
  type OwnerOrganization,
} from "@/lib/owner-runtime";

type CreateForm = {
  organizationId: string;
  provider: "meta" | "telegram";
  providerScope: string;
  scopeRef: string;
  mode: "read_only" | "live_spend";
  approvalReference: string;
  expiresAt: string;
};

type ControlsForm = {
  legalAcknowledged: boolean;
  legalReference: string;
  currency: string;
  totalBudgetMinor: string;
  dailyBudgetMinor: string;
  maxCpaMinor: string;
  minRoas: string;
  expiresAt: string;
};

const EMPTY_CREATE: CreateForm = {
  organizationId: "",
  provider: "meta",
  providerScope: "owned_assets",
  scopeRef: "",
  mode: "read_only",
  approvalReference: "",
  expiresAt: "",
};

const EMPTY_CONTROLS: ControlsForm = {
  legalAcknowledged: false,
  legalReference: "",
  currency: "",
  totalBudgetMinor: "",
  dailyBudgetMinor: "",
  maxCpaMinor: "",
  minRoas: "",
  expiresAt: "",
};

const GATE_LABELS: Array<[keyof GrowthPilotReadiness, string]> = [
  ["owner_gate", "Owner approval"],
  ["organization_gate", "Organization"],
  ["provider_scope_gate", "Provider scope"],
  ["provider_gate", "Provider verification"],
  ["execution_adapter_gate", "Execution adapter"],
  ["legal_gate", "Legal policy"],
  ["budget_gate", "Budget controls"],
  ["stop_loss_gate", "Stop-loss controls"],
  ["expiry_gate", "Pilot expiry"],
  ["launch_gate", "Launch authorization"],
];

function messageFromError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return "Owner Growth pilot operation failed.";
}

function statusClass(status: string): string {
  if (["read_only_armed", "read_only_validated"].includes(status)) {
    return "border-blue-500/20 bg-blue-500/10 text-blue-300";
  }
  if (status === "armed") {
    return "border-red-500/30 bg-red-500/10 text-red-300";
  }
  if (["disarmed", "auto_disarmed"].includes(status)) {
    return "border-orange-500/20 bg-orange-500/10 text-orange-300";
  }
  return "border-white/10 bg-white/[0.03] text-white/45";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not set";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not set" : date.toLocaleString();
}

function toLocalDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function parsePositiveSafeInteger(value: string): number | undefined {
  const clean = value.trim();
  if (!clean) return undefined;
  if (!/^\d+$/.test(clean))
    throw new Error("Budget control must be a positive integer.");
  const parsed = Number(clean);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(
      "Budget control exceeds the safe Owner console integer range.",
    );
  }
  return parsed;
}

function pilotStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    read_only_armed: "Read-only armed",
    read_only_validated: "Read-only validated",
    armed: "Live pilot armed",
    disarmed: "Disarmed",
    auto_disarmed: "Auto-disarmed",
    launch_authorized: "Launch authorized",
    owner_approved: "Owner approved",
    controls_configured: "Controls configured",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function pilotScopeLabel(scope: string): string {
  const labels: Record<string, string> = {
    owned_assets: "Owned assets",
    sandbox: "Sandbox",
    owner_bots: "Owner bots",
    managed_ad_account: "Managed ad account",
  };
  return labels[scope] ?? scope.replaceAll("_", " ");
}

function pilotModeLabel(mode: "read_only" | "live_spend"): string {
  return mode === "live_spend" ? "Live spend gate" : "Read only";
}

function readinessScore(readiness: GrowthPilotReadiness | undefined): string {
  if (!readiness) return "Readiness not loaded";
  const passed = GATE_LABELS.filter(([key]) => readiness[key] === true).length;
  return `${passed}/${GATE_LABELS.length} safety gates`;
}

export function GrowthSocialPilotConsole() {
  const { locale } = useLanguageVoice();
  const tr = useCallback(
    (value: string) => translateInterfaceText(value, locale),
    [locale],
  );
  const [pilots, setPilots] = useState<GrowthControlledPilot[]>([]);
  const [readiness, setReadiness] = useState<
    Record<string, GrowthPilotReadiness>
  >({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState("Loading controlled pilot state…");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createForm, setCreateForm] = useState<CreateForm>(EMPTY_CREATE);
  const [controls, setControls] = useState<ControlsForm>(EMPTY_CONTROLS);
  const [metaDiscovery, setMetaDiscovery] =
    useState<GrowthMetaTargetDiscovery | null>(null);
  const [organizations, setOrganizations] = useState<OwnerOrganization[]>([]);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryAttempted, setDiscoveryAttempted] = useState(false);
  const [discoveryMessage, setDiscoveryMessage] = useState(
    "Meta target discovery has not been loaded yet.",
  );

  const loadDiscovery = useCallback(async () => {
    setDiscoveryAttempted(true);
    setDiscoveryLoading(true);
    const [metaResult, runtimeResult] = await Promise.allSettled([
      fetchOwnerGrowthMetaTargets(),
      fetchOwnerRuntimeSnapshot(),
    ]);
    if (metaResult.status === "fulfilled") {
      setMetaDiscovery(metaResult.value);
      setDiscoveryMessage(
        `Discovered ${metaResult.value.account_count} owned Meta accounts; ${metaResult.value.active_account_count} active.`,
      );
    } else {
      setMetaDiscovery(null);
      setDiscoveryMessage(messageFromError(metaResult.reason));
    }
    if (runtimeResult.status === "fulfilled") {
      setOrganizations(
        runtimeResult.value.organizations.filter(
          (organization) => organization.status === "active",
        ),
      );
    } else {
      setOrganizations([]);
      if (metaResult.status === "fulfilled") {
        setDiscoveryMessage(
          "Meta targets loaded, but active AIOS organizations could not be loaded.",
        );
      }
    }
    setDiscoveryLoading(false);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchOwnerGrowthPilots();
      setPilots(response.items);
      setSelectedId((current) =>
        current && response.items.some((pilot) => pilot.id === current)
          ? current
          : (response.items[0]?.id ?? null),
      );
      const settled = await Promise.allSettled(
        response.items.map(
          async (pilot) =>
            [pilot.id, await fetchOwnerGrowthPilotReadiness(pilot.id)] as const,
        ),
      );
      const next: Record<string, GrowthPilotReadiness> = {};
      for (const result of settled) {
        if (result.status === "fulfilled")
          next[result.value[0]] = result.value[1];
      }
      setReadiness(next);
      setMessage(`Synchronized ${response.items.length} controlled pilots.`);
    } catch (error) {
      setMessage(messageFromError(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (
      createForm.mode === "live_spend" &&
      !discoveryAttempted &&
      !discoveryLoading
    ) {
      void loadDiscovery();
    }
  }, [createForm.mode, discoveryAttempted, discoveryLoading, loadDiscovery]);

  const selectedPilot = useMemo(
    () => pilots.find((pilot) => pilot.id === selectedId) ?? null,
    [pilots, selectedId],
  );

  useEffect(() => {
    if (!selectedPilot) {
      setControls(EMPTY_CONTROLS);
      return;
    }
    setControls({
      legalAcknowledged: selectedPilot.legal_policy_acknowledged,
      legalReference: selectedPilot.legal_policy_reference ?? "",
      currency: selectedPilot.currency ?? "",
      totalBudgetMinor: selectedPilot.max_total_budget_minor?.toString() ?? "",
      dailyBudgetMinor: selectedPilot.max_daily_budget_minor?.toString() ?? "",
      maxCpaMinor: selectedPilot.max_cpa_minor?.toString() ?? "",
      minRoas: selectedPilot.min_roas?.toString() ?? "",
      expiresAt: toLocalDateTime(selectedPilot.expires_at),
    });
  }, [selectedPilot]);

  const liveSpendEnabled = pilots.filter(
    (pilot) => pilot.real_spend_allowed,
  ).length;
  const liveSpendPilots = pilots.filter(
    (pilot) => pilot.mode === "live_spend",
  ).length;
  const readOnlyPilots = pilots.filter(
    (pilot) => pilot.mode === "read_only",
  ).length;
  const selectedMetaTarget =
    metaDiscovery?.accounts.find(
      (account) => account.scope_ref === createForm.scopeRef,
    ) ?? null;

  async function runPilotAction(
    pilot: GrowthControlledPilot,
    action: () => Promise<unknown>,
    successMessage: string,
  ) {
    setBusyId(pilot.id);
    setMessage("Applying Owner-controlled pilot operation…");
    try {
      await action();
      setMessage(successMessage);
      await load();
    } catch (error) {
      setMessage(messageFromError(error));
    } finally {
      setBusyId(null);
    }
  }

  async function refreshPilotReadiness(pilot: GrowthControlledPilot) {
    setBusyId(pilot.id);
    try {
      const result = await fetchOwnerGrowthPilotReadiness(pilot.id);
      setReadiness((current) => ({ ...current, [pilot.id]: result }));
      setMessage("Pilot readiness refreshed.");
    } catch (error) {
      setMessage(messageFromError(error));
    } finally {
      setBusyId(null);
    }
  }

  async function handleCreate() {
    const approvalReference = createForm.approvalReference.trim();
    if (!approvalReference) {
      setMessage("Owner approval reference is required.");
      return;
    }
    if (createForm.mode === "live_spend") {
      const organization = organizations.find(
        (item) =>
          item.id === createForm.organizationId && item.status === "active",
      );
      const target = metaDiscovery?.accounts.find(
        (item) => item.scope_ref === createForm.scopeRef,
      );
      if (!organization) {
        setMessage(
          "Select an active AIOS organization for the live-spend pilot.",
        );
        return;
      }
      if (!target?.active) {
        setMessage(
          "Select an active discovered Meta ad account for the live-spend pilot.",
        );
        return;
      }
      if (metaDiscovery?.result_page_truncated) {
        setMessage(
          "Meta target discovery is truncated; resolve the account inventory before creating a live-spend pilot.",
        );
        return;
      }
      if (
        !window.confirm(
          tr(
            "Create this live-spend pilot record? Creation does not authorize launch or spend; every safety gate remains fail-closed.",
          ),
        )
      ) {
        return;
      }
    }
    setBusyId("create");
    try {
      await createOwnerGrowthPilot({
        organization_id: createForm.organizationId.trim() || null,
        provider: createForm.provider,
        provider_scope: createForm.providerScope,
        scope_ref: createForm.scopeRef.trim() || null,
        mode: createForm.mode,
        owner_approval_reference: approvalReference,
        expires_at: createForm.expiresAt
          ? new Date(createForm.expiresAt).toISOString()
          : null,
      });
      setCreateForm(EMPTY_CREATE);
      setMessage("Controlled pilot created with spend disabled.");
      await load();
    } catch (error) {
      setMessage(messageFromError(error));
    } finally {
      setBusyId(null);
    }
  }

  async function handleControls(pilot: GrowthControlledPilot) {
    if (pilot.mode !== "live_spend") return;
    setBusyId(pilot.id);
    try {
      const totalBudget = parsePositiveSafeInteger(controls.totalBudgetMinor);
      const dailyBudget = parsePositiveSafeInteger(controls.dailyBudgetMinor);
      const maxCpa = parsePositiveSafeInteger(controls.maxCpaMinor);
      const minRoas = controls.minRoas.trim()
        ? Number(controls.minRoas.trim())
        : undefined;
      if (
        minRoas !== undefined &&
        (!Number.isFinite(minRoas) || minRoas <= 0)
      ) {
        throw new Error("Minimum ROAS must be a positive finite number.");
      }
      await configureOwnerGrowthPilot(pilot.id, {
        legal_policy_acknowledged: controls.legalAcknowledged,
        legal_policy_reference: controls.legalReference.trim() || null,
        currency: controls.currency.trim().toUpperCase() || null,
        max_total_budget_minor: totalBudget,
        max_daily_budget_minor: dailyBudget,
        max_cpa_minor: maxCpa,
        min_roas: minRoas,
        expires_at: controls.expiresAt
          ? new Date(controls.expiresAt).toISOString()
          : undefined,
      });
      setMessage(
        "Pilot controls saved. Any previous launch authorization was reset.",
      );
      await load();
    } catch (error) {
      setMessage(messageFromError(error));
    } finally {
      setBusyId(null);
    }
  }

  function setMode(mode: "read_only" | "live_spend") {
    setCreateForm((current) => {
      if (mode === "live_spend") {
        return {
          ...current,
          mode,
          provider: "meta",
          providerScope: "managed_ad_account",
          organizationId: "",
          scopeRef: "",
        };
      }
      const provider = current.provider;
      return {
        ...current,
        mode,
        providerScope: provider === "telegram" ? "owner_bots" : "owned_assets",
        organizationId: "",
        scopeRef: "",
      };
    });
  }

  function setProvider(provider: "meta" | "telegram") {
    setCreateForm((current) => ({
      ...current,
      provider,
      mode: provider === "telegram" ? "read_only" : current.mode,
      providerScope:
        provider === "telegram"
          ? "owner_bots"
          : current.mode === "live_spend"
            ? "managed_ad_account"
            : "owned_assets",
      organizationId: provider === "telegram" ? "" : current.organizationId,
      scopeRef: provider === "telegram" ? "" : current.scopeRef,
    }));
  }

  return (
    <section className="space-y-4">
      <div className="glass-card overflow-hidden border border-electric-500/15">
        <div className="border-b border-white/[0.06] bg-electric-500/[0.04] p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
                <ShieldCheck className="h-3.5 w-3.5" />
                Growth & Social Controlled Pilots
              </div>
              <h2 className="text-xl font-semibold text-white">
                GS-12 Owner Safety Console
              </h2>
              <p className="mt-1 max-w-3xl text-xs leading-5 text-white/40">
                Inspect provider readiness, validate read-only pilots, configure
                explicit live-spend controls, authorize launch, and
                emergency-disarm without bypassing backend safety gates.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading || busyId !== null}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-xs font-medium text-white/70 transition hover:bg-white/[0.08] disabled:opacity-50"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
              />
              Refresh pilot state
            </button>
          </div>
        </div>

        <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
            <Activity className="h-4 w-4 text-electric-300" />
            <div className="mt-3 text-2xl font-bold text-white">
              {pilots.length}
            </div>
            <div className="text-xs text-white/35">Controlled pilots</div>
          </div>
          <div className="rounded-xl border border-blue-500/15 bg-blue-500/[0.04] p-4">
            <FlaskConical className="h-4 w-4 text-blue-300" />
            <div className="mt-3 text-2xl font-bold text-white">
              {readOnlyPilots}
            </div>
            <div className="text-xs text-white/35">Read-only pilots</div>
          </div>
          <div className="rounded-xl border border-orange-500/15 bg-orange-500/[0.04] p-4">
            <Rocket className="h-4 w-4 text-orange-300" />
            <div className="mt-3 text-2xl font-bold text-white">
              {liveSpendPilots}
            </div>
            <div className="text-xs text-white/35">
              Live-spend pilot records
            </div>
          </div>
          <div
            className={`rounded-xl border p-4 ${liveSpendEnabled ? "border-red-500/30 bg-red-500/10" : "border-green-500/20 bg-green-500/[0.06]"}`}
          >
            <CircleDollarSign
              className={`h-4 w-4 ${liveSpendEnabled ? "text-red-300" : "text-green-300"}`}
            />
            <div className="mt-3 text-2xl font-bold text-white">
              {liveSpendEnabled}
            </div>
            <div className="text-xs text-white/35">Spend-enabled pilots</div>
          </div>
        </div>

        <div
          className={`mx-5 mb-5 flex items-start gap-3 rounded-xl border p-4 text-xs leading-5 ${liveSpendEnabled ? "border-red-500/30 bg-red-500/10 text-red-200" : "border-green-500/20 bg-green-500/[0.05] text-green-200"}`}
        >
          {liveSpendEnabled ? (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          <span>
            {liveSpendEnabled
              ? "Attention: at least one pilot is spend-enabled. Verify its expiry, budget and stop-loss gates immediately."
              : "Fail-closed: no controlled pilot currently authorizes real advertising spend."}
          </span>
        </div>

        <div className="border-t border-white/[0.06] px-5 py-3 text-xs text-electric-300">
          {message}
        </div>
      </div>

      <details className="glass-card p-5">
        <summary className="cursor-pointer text-sm font-semibold text-white">
          Create controlled pilot record
        </summary>
        <p className="mt-2 text-xs leading-5 text-white/35">
          Creating a record never authorizes launch or spend. Live-spend records
          require explicit organization and managed ad-account references and
          remain blocked until every server-side gate is green.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-1 text-xs text-white/45">
            <span>Pilot mode</span>
            <select
              value={createForm.mode}
              onChange={(event) =>
                setMode(event.target.value as CreateForm["mode"])
              }
              className="glass-input w-full rounded-xl px-3 py-2 text-white outline-none"
            >
              <option className="bg-space-800" value="read_only">
                Read only
              </option>
              <option className="bg-space-800" value="live_spend">
                Live spend gate
              </option>
            </select>
          </label>
          <label className="space-y-1 text-xs text-white/45">
            <span>Provider</span>
            <select
              value={createForm.provider}
              onChange={(event) =>
                setProvider(event.target.value as CreateForm["provider"])
              }
              className="glass-input w-full rounded-xl px-3 py-2 text-white outline-none"
            >
              <option className="bg-space-800" value="meta">
                Meta
              </option>
              <option className="bg-space-800" value="telegram">
                Telegram
              </option>
            </select>
          </label>
          <label className="space-y-1 text-xs text-white/45">
            <span>Provider scope</span>
            <select
              value={createForm.providerScope}
              onChange={(event) =>
                setCreateForm((current) => ({
                  ...current,
                  providerScope: event.target.value,
                }))
              }
              className="glass-input w-full rounded-xl px-3 py-2 text-white outline-none"
            >
              {createForm.provider === "telegram" ? (
                <option className="bg-space-800" value="owner_bots">
                  Owner bots
                </option>
              ) : createForm.mode === "live_spend" ? (
                <option className="bg-space-800" value="managed_ad_account">
                  Managed ad account
                </option>
              ) : (
                <>
                  <option className="bg-space-800" value="owned_assets">
                    Owned assets
                  </option>
                  <option className="bg-space-800" value="sandbox">
                    Sandbox
                  </option>
                </>
              )}
            </select>
          </label>
          <label className="space-y-1 text-xs text-white/45">
            <span>Expiry</span>
            <input
              type="datetime-local"
              value={createForm.expiresAt}
              onChange={(event) =>
                setCreateForm((current) => ({
                  ...current,
                  expiresAt: event.target.value,
                }))
              }
              className="glass-input w-full rounded-xl px-3 py-2 text-white outline-none"
            />
          </label>
          {createForm.mode === "live_spend" ? (
            <>
              <label className="space-y-1 text-xs text-white/45 xl:col-span-2">
                <span>AIOS organization</span>
                <select
                  value={createForm.organizationId}
                  onChange={(event) =>
                    setCreateForm((current) => ({
                      ...current,
                      organizationId: event.target.value,
                    }))
                  }
                  className="glass-input w-full rounded-xl px-3 py-2 text-white outline-none"
                >
                  <option className="bg-space-800" value="">
                    Select active organization
                  </option>
                  {organizations.map((organization) => (
                    <option
                      className="bg-space-800"
                      key={organization.id}
                      value={organization.id}
                    >
                      {organization.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs text-white/45 xl:col-span-2">
                <span>Discovered managed Meta account</span>
                <select
                  value={createForm.scopeRef}
                  onChange={(event) =>
                    setCreateForm((current) => ({
                      ...current,
                      scopeRef: event.target.value,
                    }))
                  }
                  className="glass-input w-full rounded-xl px-3 py-2 text-white outline-none"
                >
                  <option className="bg-space-800" value="">
                    Select active Meta account
                  </option>
                  {metaDiscovery?.accounts.map((account) => (
                    <option
                      className="bg-space-800"
                      disabled={!account.active}
                      key={account.scope_ref}
                      value={account.scope_ref}
                    >
                      {account.name} · {account.currency ?? "—"} ·{" "}
                      {account.timezone_name ?? "—"} ·{" "}
                      {account.active ? "Active" : "Inactive"}
                    </option>
                  ))}
                </select>
              </label>
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 text-xs leading-5 text-white/45 md:col-span-2 xl:col-span-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div className="flex items-start gap-2">
                    <Target className="mt-0.5 h-4 w-4 shrink-0 text-electric-300" />
                    <div>
                      <div className="font-medium text-white/70">
                        Read-only Meta target discovery
                      </div>
                      <div className="mt-1 text-white/35">
                        {discoveryMessage} Raw account IDs and credentials are
                        never returned to this console.
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void loadDiscovery()}
                    disabled={discoveryLoading}
                    className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-white/60 disabled:opacity-50"
                  >
                    <RefreshCw
                      className={`h-3 w-3 ${discoveryLoading ? "animate-spin" : ""}`}
                    />
                    Refresh Meta targets
                  </button>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  <div>
                    ads_read:{" "}
                    {String(metaDiscovery?.permissions.ads_read ?? false)}
                  </div>
                  <div
                    className={
                      metaDiscovery?.permissions.ads_management
                        ? "text-green-300"
                        : "text-orange-300"
                    }
                  >
                    ads_management:{" "}
                    {String(metaDiscovery?.permissions.ads_management ?? false)}
                  </div>
                  <div>
                    Active targets: {metaDiscovery?.active_account_count ?? 0}
                  </div>
                </div>
                {metaDiscovery?.result_page_truncated ? (
                  <div className="mt-2 text-orange-300">
                    Meta returned a truncated account inventory. Live-spend
                    pilot creation is blocked until the full target list is
                    resolved.
                  </div>
                ) : null}
                {selectedMetaTarget ? (
                  <div className="mt-2 text-electric-300">
                    Selected target: {selectedMetaTarget.name} ·{" "}
                    {selectedMetaTarget.currency ?? "—"} ·{" "}
                    {selectedMetaTarget.timezone_name ?? "—"}
                  </div>
                ) : null}
                {!metaDiscovery?.permissions.ads_management ? (
                  <div className="mt-2 text-orange-300">
                    The current owned Meta token is read-only. You may prepare a
                    fail-closed pilot record after selecting the target, but
                    live owned-account write validation remains blocked until
                    ads_management is granted.
                  </div>
                ) : null}
              </div>
            </>
          ) : null}
          <label className="space-y-1 text-xs text-white/45 md:col-span-2 xl:col-span-4">
            <span>Owner approval reference</span>
            <input
              value={createForm.approvalReference}
              onChange={(event) =>
                setCreateForm((current) => ({
                  ...current,
                  approvalReference: event.target.value,
                }))
              }
              placeholder="Audit reference only — never credential material"
              className="glass-input w-full rounded-xl px-3 py-2 text-white outline-none"
            />
          </label>
        </div>
        <button
          type="button"
          onClick={() => void handleCreate()}
          disabled={busyId !== null}
          className="mt-4 inline-flex items-center gap-2 rounded-xl bg-electric-500/15 px-4 py-2 text-xs font-medium text-electric-200 disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" />
          Create fail-closed pilot
        </button>
      </details>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-3">
          {loading ? (
            <div className="glass-card p-8 text-center text-sm text-white/40">
              Loading controlled pilots…
            </div>
          ) : pilots.length === 0 ? (
            <div className="glass-card p-8 text-center text-sm text-white/40">
              No controlled pilots are registered.
            </div>
          ) : (
            pilots.map((pilot) => {
              const state = readiness[pilot.id];
              const selected = pilot.id === selectedId;
              const busy = busyId === pilot.id;
              return (
                <article
                  key={pilot.id}
                  className={`glass-card cursor-pointer border p-5 transition ${selected ? "border-electric-500/25" : "border-white/[0.05]"}`}
                  onClick={() => setSelectedId(pilot.id)}
                >
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold capitalize text-white">
                          {pilot.provider} ·{" "}
                          {pilotScopeLabel(pilot.provider_scope)}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] ${statusClass(pilot.status)}`}
                        >
                          {pilotStatusLabel(pilot.status)}
                        </span>
                        <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-white/40">
                          {pilotModeLabel(pilot.mode)}
                        </span>
                      </div>
                      <div className="mt-2 text-xs text-white/35">
                        {pilot.capability} · Expires{" "}
                        {formatDate(pilot.expires_at)}
                      </div>
                      <div className="mt-1 text-xs text-electric-300">
                        {readinessScore(state)}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void refreshPilotReadiness(pilot);
                        }}
                        disabled={busy}
                        className="rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-white/60 disabled:opacity-50"
                      >
                        Refresh gates
                      </button>
                      {pilot.mode === "read_only" ? (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            void runPilotAction(
                              pilot,
                              () => validateOwnerGrowthPilotReadOnly(pilot.id),
                              "Live read-only validation completed without provider mutation.",
                            );
                          }}
                          disabled={busy}
                          className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-1.5 text-[11px] text-blue-200 disabled:opacity-50"
                        >
                          Validate read only
                        </button>
                      ) : null}
                    </div>
                  </div>

                  {state ? (
                    <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-5">
                      {GATE_LABELS.map(([key, label]) => {
                        const passed = state[key] === true;
                        return (
                          <div
                            key={key}
                            className={`flex items-center gap-1.5 rounded-lg border px-2 py-1.5 text-[10px] ${passed ? "border-green-500/15 bg-green-500/[0.05] text-green-300" : "border-white/[0.07] bg-white/[0.02] text-white/35"}`}
                          >
                            {passed ? (
                              <CheckCircle2 className="h-3 w-3 shrink-0" />
                            ) : (
                              <XCircle className="h-3 w-3 shrink-0" />
                            )}
                            <span>{label}</span>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}

                  {state?.blocked_reasons.length ? (
                    <div
                      className="mt-3 flex flex-wrap gap-1.5"
                      data-no-translate
                    >
                      {state.blocked_reasons.map((reason) => (
                        <code
                          key={reason}
                          className="rounded-md border border-orange-500/10 bg-orange-500/[0.05] px-2 py-1 text-[10px] text-orange-200/80"
                        >
                          {reason}
                        </code>
                      ))}
                    </div>
                  ) : null}
                </article>
              );
            })
          )}
        </div>

        <aside className="glass-card h-fit p-5 xl:sticky xl:top-4">
          {!selectedPilot ? (
            <div className="py-8 text-center text-sm text-white/40">
              Select a pilot to inspect Owner controls.
            </div>
          ) : (
            <div className="space-y-5">
              <div>
                <div className="text-xs uppercase tracking-[0.16em] text-electric-300">
                  Selected pilot
                </div>
                <div className="mt-2 text-lg font-semibold capitalize text-white">
                  {selectedPilot.provider} ·{" "}
                  {pilotScopeLabel(selectedPilot.provider_scope)}
                </div>
                <div className="mt-1 text-xs text-white/35">
                  {pilotStatusLabel(selectedPilot.status)} ·{" "}
                  {readinessScore(readiness[selectedPilot.id])}
                </div>
              </div>

              {selectedPilot.mode === "live_spend" ? (
                <div className="space-y-3 border-t border-white/[0.06] pt-4">
                  <div className="flex items-center gap-2 text-xs font-semibold text-white">
                    <CircleDollarSign className="h-4 w-4 text-orange-300" />
                    Explicit spend controls
                  </div>
                  <label className="flex items-center gap-2 text-xs text-white/50">
                    <input
                      type="checkbox"
                      checked={controls.legalAcknowledged}
                      onChange={(event) =>
                        setControls((current) => ({
                          ...current,
                          legalAcknowledged: event.target.checked,
                        }))
                      }
                    />
                    Legal and policy review acknowledged
                  </label>
                  <input
                    value={controls.legalReference}
                    onChange={(event) =>
                      setControls((current) => ({
                        ...current,
                        legalReference: event.target.value,
                      }))
                    }
                    placeholder="Legal/policy audit reference"
                    className="glass-input w-full rounded-xl px-3 py-2 text-xs text-white outline-none"
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      value={controls.currency}
                      maxLength={3}
                      onChange={(event) =>
                        setControls((current) => ({
                          ...current,
                          currency: event.target.value.toUpperCase(),
                        }))
                      }
                      placeholder="Currency"
                      className="glass-input rounded-xl px-3 py-2 text-xs text-white outline-none"
                    />
                    <input
                      type="datetime-local"
                      value={controls.expiresAt}
                      onChange={(event) =>
                        setControls((current) => ({
                          ...current,
                          expiresAt: event.target.value,
                        }))
                      }
                      className="glass-input rounded-xl px-3 py-2 text-xs text-white outline-none"
                    />
                  </div>
                  <p className="text-[10px] leading-4 text-white/30">
                    Budget fields use integer minor units only. The console
                    rejects values outside JavaScript safe-integer precision
                    before sending them.
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      inputMode="numeric"
                      value={controls.totalBudgetMinor}
                      onChange={(event) =>
                        setControls((current) => ({
                          ...current,
                          totalBudgetMinor: event.target.value,
                        }))
                      }
                      placeholder="Maximum total budget"
                      className="glass-input rounded-xl px-3 py-2 text-xs text-white outline-none"
                    />
                    <input
                      inputMode="numeric"
                      value={controls.dailyBudgetMinor}
                      onChange={(event) =>
                        setControls((current) => ({
                          ...current,
                          dailyBudgetMinor: event.target.value,
                        }))
                      }
                      placeholder="Maximum daily budget"
                      className="glass-input rounded-xl px-3 py-2 text-xs text-white outline-none"
                    />
                    <input
                      inputMode="numeric"
                      value={controls.maxCpaMinor}
                      onChange={(event) =>
                        setControls((current) => ({
                          ...current,
                          maxCpaMinor: event.target.value,
                        }))
                      }
                      placeholder="Maximum CPA"
                      className="glass-input rounded-xl px-3 py-2 text-xs text-white outline-none"
                    />
                    <input
                      inputMode="decimal"
                      value={controls.minRoas}
                      onChange={(event) =>
                        setControls((current) => ({
                          ...current,
                          minRoas: event.target.value,
                        }))
                      }
                      placeholder="Minimum ROAS"
                      className="glass-input rounded-xl px-3 py-2 text-xs text-white outline-none"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleControls(selectedPilot)}
                    disabled={busyId === selectedPilot.id}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-xs font-medium text-white/70 disabled:opacity-50"
                  >
                    <Save className="h-3.5 w-3.5" />
                    Save controls and reset launch authorization
                  </button>
                </div>
              ) : null}

              <div className="space-y-2 border-t border-white/[0.06] pt-4">
                {selectedPilot.mode === "live_spend" ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (
                        window.confirm(
                          tr(
                            "Authorize launch for this pilot? Authorization alone does not execute a provider call or spend, and the backend will reject it unless every pre-launch gate is green.",
                          ),
                        )
                      ) {
                        void runPilotAction(
                          selectedPilot,
                          () =>
                            authorizeOwnerGrowthPilotLaunch(selectedPilot.id),
                          "Launch authorization recorded. Provider spend has not been executed.",
                        );
                      }
                    }}
                    disabled={
                      busyId === selectedPilot.id ||
                      selectedPilot.launch_authorized
                    }
                    className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-orange-500/20 bg-orange-500/[0.06] px-4 py-2 text-xs font-medium text-orange-200 disabled:opacity-40"
                  >
                    <Rocket className="h-3.5 w-3.5" />
                    Authorize launch gate
                  </button>
                ) : null}

                <button
                  type="button"
                  onClick={() => {
                    const state = readiness[selectedPilot.id];
                    if (!state?.ready_to_arm) {
                      setMessage(
                        "Pilot cannot be armed while safety gates are blocked.",
                      );
                      return;
                    }
                    if (selectedPilot.mode === "live_spend") {
                      const phrase = window.prompt(
                        tr(
                          "Type ARM LIVE SPEND to arm this pilot. Arming still does not create an ad; all future provider execution must pass the runtime guard.",
                        ),
                      );
                      if (phrase !== "ARM LIVE SPEND") {
                        setMessage(
                          "Live-spend arming cancelled because the confirmation phrase did not match.",
                        );
                        return;
                      }
                    }
                    void runPilotAction(
                      selectedPilot,
                      () => armOwnerGrowthPilot(selectedPilot.id),
                      selectedPilot.mode === "live_spend"
                        ? "Pilot armed under server runtime guard. No provider action was executed by this button."
                        : "Read-only pilot armed with mutation and spend disabled.",
                    );
                  }}
                  disabled={
                    busyId === selectedPilot.id ||
                    !readiness[selectedPilot.id]?.ready_to_arm
                  }
                  className={`inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2 text-xs font-medium disabled:opacity-40 ${selectedPilot.mode === "live_spend" ? "border border-red-500/25 bg-red-500/[0.07] text-red-200" : "border border-blue-500/20 bg-blue-500/[0.07] text-blue-200"}`}
                >
                  <ShieldCheck className="h-3.5 w-3.5" />
                  {selectedPilot.mode === "live_spend"
                    ? "Arm runtime-guarded live pilot"
                    : "Arm read-only pilot"}
                </button>

                <button
                  type="button"
                  onClick={() => {
                    const reason = window.prompt(
                      tr("Disarm reason for the audit log:"),
                      "owner-emergency-disarm",
                    );
                    if (!reason?.trim()) return;
                    void runPilotAction(
                      selectedPilot,
                      () =>
                        disarmOwnerGrowthPilot(selectedPilot.id, reason.trim()),
                      "Pilot disarmed and launch/spend authorization cleared.",
                    );
                  }}
                  disabled={busyId === selectedPilot.id}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-xs font-medium text-white/55 disabled:opacity-40"
                >
                  <Ban className="h-3.5 w-3.5" />
                  Emergency disarm
                </button>
              </div>

              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3 text-[10px] leading-4 text-white/35">
                <div>
                  Real spend allowed: {String(selectedPilot.real_spend_allowed)}
                </div>
                <div>
                  Live mutation allowed:{" "}
                  {String(selectedPilot.live_provider_mutation_allowed)}
                </div>
                <div>
                  Automatic execution allowed:{" "}
                  {String(selectedPilot.automatic_execution_allowed)}
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
