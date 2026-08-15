"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Edit3,
  KeyRound,
  LockKeyhole,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  UserRound,
  Users,
  XCircle,
} from "lucide-react";

import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import { translateInterfaceText } from "@/lib/interface-translations";
import {
  clearOwnerGrowthAccess,
  fetchOwnerGrowthAccessOverrides,
  fetchOwnerGrowthCapabilities,
  setOwnerGrowthAccess,
  type GrowthAccessOverride,
  type GrowthCapabilityDefinition,
} from "@/lib/owner-growth-social";
import {
  fetchOwnerRuntimeSnapshot,
  type OwnerOrganization,
  type OwnerRuntimeSnapshot,
  type OwnerUser,
} from "@/lib/owner-runtime";

type TargetScope = "user" | "organization";
type Decision = "grant" | "deny";

const EMPTY_RUNTIME: OwnerRuntimeSnapshot = {
  generatedAt: "",
  projects: [],
  organizations: [],
  users: [],
};

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Owner request failed";
}

function targetLabel(target: OwnerUser | OwnerOrganization): string {
  if ("email" in target) {
    return `${target.name} · ${target.email} · ${target.organization}`;
  }
  return `${target.name} · ${target.status}`;
}

function safeLimitsJson(value: string): Record<string, unknown> {
  if (new TextEncoder().encode(value).length > 4096) {
    throw new Error("Limits JSON must be 4096 bytes or less.");
  }
  const parsed: unknown = JSON.parse(value || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Limits must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function decisionClass(allowed: boolean) {
  return allowed
    ? "border-green-500/20 bg-green-500/10 text-green-300"
    : "border-red-500/20 bg-red-500/10 text-red-300";
}

export function GrowthSocialAccessConsole() {
  const { locale } = useLanguageVoice();
  const t = useCallback(
    (text: string) => translateInterfaceText(text, locale),
    [locale],
  );

  const [capabilities, setCapabilities] = useState<
    GrowthCapabilityDefinition[]
  >([]);
  const [overrides, setOverrides] = useState<GrowthAccessOverride[]>([]);
  const [runtime, setRuntime] = useState<OwnerRuntimeSnapshot>(EMPTY_RUNTIME);
  const [invalidRecords, setInvalidRecords] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(
    "Loading Growth & Social access authority…",
  );

  const [scope, setScope] = useState<TargetScope>("user");
  const [subjectId, setSubjectId] = useState("");
  const [capability, setCapability] = useState("");
  const [decision, setDecision] = useState<Decision>("grant");
  const [approvalRequired, setApprovalRequired] = useState(false);
  const [limitsText, setLimitsText] = useState("{}");
  const [selectedOverride, setSelectedOverride] =
    useState<GrowthAccessOverride | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [catalogue, access, snapshot] = await Promise.all([
        fetchOwnerGrowthCapabilities(),
        fetchOwnerGrowthAccessOverrides(),
        fetchOwnerRuntimeSnapshot(),
      ]);
      setCapabilities(catalogue);
      setOverrides(access.items);
      setInvalidRecords(access.invalid_records);
      setRuntime(snapshot);
      if (!capability && catalogue[0]) setCapability(catalogue[0].id);
      setMessage("Growth & Social Owner access synchronized.");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [capability]);

  useEffect(() => {
    void load();
  }, [load]);

  const targets = useMemo(() => {
    const values = scope === "user" ? runtime.users : runtime.organizations;
    return [...values].sort((left, right) =>
      left.name.localeCompare(right.name),
    );
  }, [runtime.organizations, runtime.users, scope]);

  useEffect(() => {
    if (selectedOverride) return;
    if (!targets.some((target) => target.id === subjectId)) {
      setSubjectId(targets[0]?.id ?? "");
    }
  }, [selectedOverride, subjectId, targets]);

  const summary = useMemo(
    () => ({
      grants: overrides.filter((item) => item.allowed).length,
      denies: overrides.filter((item) => !item.allowed).length,
      approvals: overrides.filter((item) => item.approval_required).length,
      targets: new Set(
        overrides.map((item) => `${item.scope}:${item.subject_id}`),
      ).size,
    }),
    [overrides],
  );

  function resetForm() {
    setSelectedOverride(null);
    setScope("user");
    setSubjectId(runtime.users[0]?.id ?? "");
    setCapability(capabilities[0]?.id ?? "");
    setDecision("grant");
    setApprovalRequired(false);
    setLimitsText("{}");
  }

  function editOverride(item: GrowthAccessOverride) {
    setSelectedOverride(item);
    setScope(item.scope);
    setSubjectId(item.subject_id);
    setCapability(item.capability);
    setDecision(item.allowed ? "grant" : "deny");
    setApprovalRequired(item.approval_required);
    setLimitsText(JSON.stringify(item.limits, null, 2));
    setMessage("Existing Owner override loaded for editing.");
  }

  async function saveOverride() {
    if (!subjectId || !capability) {
      setMessage("Select a target and capability first.");
      return;
    }
    if (selectedOverride?.subject_status === "missing") {
      setMessage("A missing subject override can only be cleared.");
      return;
    }
    if (selectedOverride?.limits_redacted) {
      setMessage(
        "Redacted legacy limits cannot be overwritten from the console; clear this override instead.",
      );
      return;
    }

    let limits: Record<string, unknown>;
    try {
      limits = safeLimitsJson(limitsText);
    } catch (error) {
      setMessage(errorMessage(error));
      return;
    }

    const allowed = decision === "grant";
    const prompt =
      capability === "ads.manage" && allowed
        ? t(
            "Grant the AIOS ads.manage application capability? This does not authorize Meta provider mutation or real advertising spend; every GS-12 live-pilot gate remains separate and fail-closed.",
          )
        : allowed
          ? t("Save this Owner capability grant?")
          : t(
              "Save this Owner capability deny? Owner deny takes precedence over plan entitlement.",
            );
    if (!window.confirm(prompt)) return;

    setBusy(true);
    setMessage("Saving Owner Growth & Social access override…");
    try {
      await setOwnerGrowthAccess({
        scope,
        subject_id: subjectId,
        capability,
        allowed,
        approval_required: approvalRequired,
        limits,
      });
      await load();
      setMessage(
        allowed
          ? "Owner capability grant saved. Provider mutation and spend remain separately gated."
          : "Owner capability deny saved and takes precedence immediately.",
      );
      resetForm();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function clearOverride(item: GrowthAccessOverride) {
    if (
      !window.confirm(
        t(
          "Clear this Owner override? The capability will fall back to any remaining user/organization override or plan entitlement.",
        ),
      )
    ) {
      return;
    }
    setBusy(true);
    setMessage("Clearing Owner Growth & Social access override…");
    try {
      await clearOwnerGrowthAccess({
        scope: item.scope,
        subject_id: item.subject_id,
        capability: item.capability,
      });
      await load();
      setMessage("Owner capability override cleared.");
      if (selectedOverride?.record_id === item.record_id) resetForm();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-300">
            <ShieldCheck className="h-3.5 w-3.5" /> Growth &amp; Social Owner
            Authority
          </div>
          <h2 className="text-2xl font-bold text-white">
            Capability Grants, Denies &amp; Approval Gates
          </h2>
          <p className="mt-2 max-w-4xl text-sm text-white/45">
            Control Growth &amp; Social capabilities per user or organization
            independently of plan defaults. User overrides take precedence over
            organization overrides, and Owner deny takes precedence over plan
            entitlement.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading || busy}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className="h-4 w-4" /> Refresh access authority
        </button>
      </div>

      <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
        <div className="flex items-start gap-3">
          <LockKeyhole className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <div className="font-semibold">
              Application access is not live-spend authorization
            </div>
            <p className="mt-1 text-xs text-amber-100/70">
              Granting ads.manage only enables the AIOS application capability.
              It cannot bypass Meta credential verification, GS-12
              legal/budget/stop-loss gates, launch authorization, runtime
              authorization, or the automatic disarm watchdog.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {[
          { label: "Owner grants", value: summary.grants, icon: CheckCircle2 },
          { label: "Owner denies", value: summary.denies, icon: XCircle },
          { label: "Approval-gated", value: summary.approvals, icon: KeyRound },
          { label: "Managed targets", value: summary.targets, icon: Users },
        ].map((item) => (
          <div key={item.label} className="glass-card p-4">
            <item.icon className="h-5 w-5 text-cyan-300" />
            <div className="mt-3 text-2xl font-bold text-white">
              {item.value}
            </div>
            <div className="mt-1 text-xs text-white/35">{item.label}</div>
          </div>
        ))}
      </div>

      {invalidRecords > 0 && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-300">
          <AlertTriangle className="mr-2 inline h-4 w-4" />
          Some legacy override records are malformed and were hidden from this
          console. Review server audit records before cleanup.
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="glass-card p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-white">
                {selectedOverride
                  ? "Edit Owner override"
                  : "Create Owner override"}
              </h3>
              <p className="mt-1 text-xs text-white/35">
                Targets come from the live Owner runtime snapshot. Raw
                credential material is rejected by the backend and must never be
                placed in limits.
              </p>
            </div>
            {selectedOverride && (
              <button
                type="button"
                onClick={resetForm}
                className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/55 hover:bg-white/[0.04]"
              >
                <RotateCcw className="mr-1 inline h-3.5 w-3.5" /> New override
              </button>
            )}
          </div>

          <div className="mt-5 space-y-4">
            <label className="block text-xs text-white/45">
              Target scope
              <select
                value={scope}
                onChange={(event) => {
                  setScope(event.target.value as TargetScope);
                  setSelectedOverride(null);
                  setSubjectId("");
                }}
                disabled={busy || Boolean(selectedOverride)}
                className="glass-input mt-2 w-full rounded-xl px-3 py-2.5 text-sm text-white outline-none"
              >
                <option value="user" className="bg-space-800">
                  User
                </option>
                <option value="organization" className="bg-space-800">
                  Organization
                </option>
              </select>
            </label>

            <label className="block text-xs text-white/45">
              Target
              <select
                value={subjectId}
                onChange={(event) => setSubjectId(event.target.value)}
                disabled={busy || Boolean(selectedOverride)}
                className="glass-input mt-2 w-full rounded-xl px-3 py-2.5 text-sm text-white outline-none"
              >
                {selectedOverride &&
                  !targets.some((target) => target.id === subjectId) && (
                    <option value={subjectId} className="bg-space-800">
                      {selectedOverride.subject_name ?? "Missing target"} ·{" "}
                      {subjectId}
                    </option>
                  )}
                {targets.map((target) => (
                  <option
                    key={target.id}
                    value={target.id}
                    className="bg-space-800"
                  >
                    {targetLabel(target)}
                  </option>
                ))}
              </select>
            </label>

            <label className="block text-xs text-white/45">
              Growth &amp; Social capability
              <select
                value={capability}
                onChange={(event) => setCapability(event.target.value)}
                disabled={busy || Boolean(selectedOverride)}
                className="glass-input mt-2 w-full rounded-xl px-3 py-2.5 text-sm text-white outline-none"
              >
                {capabilities.map((item) => (
                  <option
                    key={item.id}
                    value={item.id}
                    className="bg-space-800"
                  >
                    {item.id}
                    {item.approval_default ? " · approval by default" : ""}
                  </option>
                ))}
              </select>
            </label>

            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setDecision("grant")}
                disabled={busy}
                className={`rounded-xl border px-4 py-3 text-sm font-medium ${
                  decision === "grant"
                    ? "border-green-500/30 bg-green-500/15 text-green-300"
                    : "border-white/10 bg-white/[0.02] text-white/40"
                }`}
              >
                <CheckCircle2 className="mr-2 inline h-4 w-4" /> Grant
              </button>
              <button
                type="button"
                onClick={() => setDecision("deny")}
                disabled={busy}
                className={`rounded-xl border px-4 py-3 text-sm font-medium ${
                  decision === "deny"
                    ? "border-red-500/30 bg-red-500/15 text-red-300"
                    : "border-white/10 bg-white/[0.02] text-white/40"
                }`}
              >
                <XCircle className="mr-2 inline h-4 w-4" /> Deny
              </button>
            </div>

            <label className="flex items-start gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-xs text-white/55">
              <input
                type="checkbox"
                checked={approvalRequired}
                onChange={(event) => setApprovalRequired(event.target.checked)}
                disabled={busy}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium text-white/75">
                  Require approval for this capability
                </span>
                <span className="mt-1 block text-white/35">
                  The capability can be granted while still requiring an
                  explicit approval workflow before its protected action.
                </span>
              </span>
            </label>

            <label className="block text-xs text-white/45">
              Capability limits JSON
              <textarea
                value={limitsText}
                onChange={(event) => setLimitsText(event.target.value)}
                disabled={busy || Boolean(selectedOverride?.limits_redacted)}
                rows={6}
                spellCheck={false}
                className="glass-input mt-2 w-full rounded-xl px-3 py-2.5 font-mono text-xs text-white outline-none"
              />
              <span className="mt-1 block text-[11px] text-white/30">
                Maximum 4096 bytes. Token, password, secret, API key,
                authorization and credential fields are rejected server-side.
              </span>
            </label>

            {selectedOverride?.limits_redacted && (
              <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-300">
                This legacy record contains unsafe or invalid limits and is
                redacted. Clear the override instead of overwriting it from the
                console.
              </div>
            )}

            <button
              type="button"
              onClick={() => void saveOverride()}
              disabled={
                busy ||
                loading ||
                !subjectId ||
                !capability ||
                selectedOverride?.subject_status === "missing" ||
                Boolean(selectedOverride?.limits_redacted)
              }
              className="btn-primary w-full justify-center disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Save className="h-4 w-4" /> Save Owner override
            </button>
          </div>
        </div>

        <div className="glass-card p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-sm font-semibold text-white">
                Current Owner overrides
              </h3>
              <p className="mt-1 text-xs text-white/35">
                These records supersede plan defaults for their exact user or
                organization capability.
              </p>
            </div>
            <div className="text-xs text-cyan-300">
              {loading ? "Loading access overrides…" : message}
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {!loading && overrides.length === 0 && (
              <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-6 text-center text-sm text-white/35">
                No Growth &amp; Social Owner overrides are registered.
              </div>
            )}
            {overrides.map((item) => (
              <div
                key={item.record_id}
                className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {item.scope === "user" ? (
                        <UserRound className="h-4 w-4 text-cyan-300" />
                      ) : (
                        <Building2 className="h-4 w-4 text-cyan-300" />
                      )}
                      <span className="break-words text-sm font-semibold text-white">
                        {item.subject_name ?? "Missing target"}
                      </span>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] ${decisionClass(item.allowed)}`}
                      >
                        {item.allowed ? "Grant" : "Deny"}
                      </span>
                      {item.approval_required && (
                        <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                          Approval required
                        </span>
                      )}
                    </div>
                    <div className="mt-1 break-all text-xs text-white/35">
                      {item.subject_detail ?? item.subject_id} ·{" "}
                      {item.subject_status}
                    </div>
                    <div className="mt-2 font-mono text-xs text-cyan-200/80">
                      {item.capability}
                    </div>
                    {item.capability === "ads.manage" && item.allowed && (
                      <div className="mt-2 text-xs text-amber-300">
                        App capability only — live provider spend remains
                        controlled by GS-12.
                      </div>
                    )}
                    <pre className="mt-3 max-h-32 overflow-auto rounded-lg border border-white/[0.04] bg-black/10 p-2 text-[10px] text-white/35">
                      {item.limits_redacted
                        ? JSON.stringify({ redacted: true }, null, 2)
                        : JSON.stringify(item.limits, null, 2)}
                    </pre>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      onClick={() => editOverride(item)}
                      disabled={busy}
                      className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/55 hover:bg-white/[0.04] disabled:opacity-40"
                    >
                      <Edit3 className="mr-1 inline h-3.5 w-3.5" /> Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => void clearOverride(item)}
                      disabled={busy}
                      className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300 disabled:opacity-40"
                    >
                      <Trash2 className="mr-1 inline h-3.5 w-3.5" /> Clear
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
