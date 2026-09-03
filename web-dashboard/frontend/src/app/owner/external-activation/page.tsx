"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  Ban,
  CheckCircle2,
  CircleDashed,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import { translateInterfaceText } from "@/lib/interface-translations";

import {
  fetchOwnerExternalActivation,
  type ExternalActivationGate,
  type ExternalActivationSnapshot,
  type ExternalActivationStatus,
} from "@/lib/owner-external-activation";

const statusMeta: Record<
  ExternalActivationStatus,
  { label: string; className: string; icon: typeof CheckCircle2 }
> = {
  satisfied_runtime: {
    label: "Satisfied by live runtime evidence",
    className: "border-green-500/20 bg-green-500/10 text-green-300",
    icon: CheckCircle2,
  },
  enforced_internal_external_pending: {
    label: "Internally enforced · external evidence pending",
    className: "border-amber-500/20 bg-amber-500/10 text-amber-200",
    icon: ShieldCheck,
  },
  blocked_external: {
    label: "Blocked on external authority / infrastructure",
    className: "border-red-500/20 bg-red-500/10 text-red-200",
    icon: AlertTriangle,
  },
  excluded_current_scope: {
    label: "Excluded from current closeout scope",
    className: "border-white/10 bg-white/[0.03] text-white/45",
    icon: Ban,
  },
};

function label(value: string) {
  return value
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function evidenceValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value === null || value === undefined || value === "") return "none";
  return String(value);
}

function GateCard({
  gate,
  t,
}: {
  gate: ExternalActivationGate;
  t: (text: string) => string;
}) {
  const meta = statusMeta[gate.status];
  const StatusIcon = meta.icon;
  const liveEntries = Object.entries(gate.live_evidence);

  return (
    <article className="glass-card space-y-5 p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="break-words text-base font-semibold text-white">
            {label(gate.gate_id)}
          </h2>
          <p className="mt-1 break-all font-mono text-[10px] text-white/30">
            {gate.gate_id}
          </p>
        </div>
        <span
          className={`inline-flex w-fit shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-medium ${meta.className}`}
        >
          <StatusIcon className="h-3.5 w-3.5" />
          {t(meta.label)}
        </span>
      </div>

      <p className="text-xs leading-6 text-white/55">{gate.external_fact}</p>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold text-white/70">
            {t("Required external evidence")}
          </h3>
          <ul className="mt-2 space-y-1.5 text-xs leading-5 text-white/40">
            {gate.evidence_requirements.map((item) => (
              <li key={item} className="flex gap-2">
                <CircleDashed className="mt-1 h-3 w-3 shrink-0 text-amber-300" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="text-xs font-semibold text-white/70">
            {t("Internal fail-closed controls")}
          </h3>
          <ul className="mt-2 space-y-1.5 text-xs leading-5 text-white/40">
            {gate.internal_controls.map((item) => (
              <li key={item} className="flex gap-2">
                <BadgeCheck className="mt-1 h-3 w-3 shrink-0 text-green-300" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {liveEntries.length > 0 && (
        <div className="rounded-xl border border-electric-500/10 bg-electric-500/5 p-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-electric-300">
            {t("Live evidence")}
          </div>
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
            {liveEntries.map(([key, value]) => (
              <div key={key} className="min-w-0">
                <dt className="text-[10px] text-white/30">
                  {key.replaceAll("_", " ")}
                </dt>
                <dd className="mt-0.5 break-words text-xs text-white/65">
                  {evidenceValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-[10px] text-white/35">
        {gate.batch_ids.map((item) => (
          <span
            key={item}
            className="rounded-full border border-white/[0.07] px-2 py-1"
          >
            {item}
          </span>
        ))}
        {gate.capability_ids.slice(0, 8).map((item) => (
          <span key={item} className="rounded-full bg-white/[0.035] px-2 py-1">
            {item}
          </span>
        ))}
        {gate.capability_ids.length > 8 && (
          <span className="rounded-full bg-white/[0.035] px-2 py-1">
            +{gate.capability_ids.length - 8} capabilities
          </span>
        )}
      </div>
    </article>
  );
}

export default function OwnerExternalActivationPage() {
  const { locale } = useLanguageVoice();
  const t = useCallback(
    (text: string) => translateInterfaceText(text, locale),
    [locale],
  );
  const [snapshot, setSnapshot] = useState<ExternalActivationSnapshot | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading external activation truth…");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const result = await fetchOwnerExternalActivation(signal);
      setSnapshot(result);
      setMessage(
        "External activation ledger synchronized with live runtime evidence.",
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setMessage("External activation ledger could not be loaded.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const gates = snapshot?.gates ?? [];
  const inScope = useMemo(
    () => gates.filter((gate) => !gate.excluded_from_current_scope),
    [gates],
  );

  return (
    <div className="space-y-6">
      <header className="glass-card p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex gap-3">
            <ShieldCheck className="mt-1 h-7 w-7 shrink-0 text-electric-300" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-electric-300">
                {t("External Activation Truth Ledger")}
              </p>
              <h1 className="mt-2 text-3xl font-bold text-white">
                {t("External Activation")}
              </h1>
              <p className="mt-2 max-w-4xl text-sm leading-relaxed text-white/45">
                {t(
                  "Read-only evidence view. No generic override exists: every external gate remains fail-closed until its own runtime, legal, financial, device, or infrastructure evidence is real. Store publication and direct Apple Pay are excluded from the current closeout scope by Owner decision.",
                )}
              </p>
            </div>
          </div>
          <button
            type="button"
            className="btn-secondary"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("Refresh")}
          </button>
        </div>
      </header>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="glass-card p-5">
          <div className="text-3xl font-bold text-white">
            {snapshot?.counts.in_scope_gates ?? 0}
          </div>
          <div className="mt-1 text-xs text-white/40">
            {t("In-scope external gates")}
          </div>
        </div>
        <div className="glass-card p-5">
          <div className="text-3xl font-bold text-green-300">
            {snapshot?.counts.satisfied_runtime ?? 0}
          </div>
          <div className="mt-1 text-xs text-white/40">
            {t("Satisfied by live evidence")}
          </div>
        </div>
        <div className="glass-card p-5">
          <div className="text-3xl font-bold text-amber-200">
            {snapshot?.counts.enforced_internal_external_pending ?? 0}
          </div>
          <div className="mt-1 text-xs text-white/40">
            {t("Internally enforced · external pending")}
          </div>
        </div>
        <div className="glass-card p-5">
          <div className="text-3xl font-bold text-red-200">
            {snapshot?.counts.blocked_external ?? 0}
          </div>
          <div className="mt-1 text-xs text-white/40">
            {t("Blocked on external facts")}
          </div>
        </div>
      </section>

      <section className="glass-card p-4 text-xs leading-6 text-electric-200/80">
        {t(message)}
        {snapshot && (
          <span className="ms-2 text-white/30">
            {inScope.length} {t("active gates ·")}{" "}
            {snapshot.counts.excluded_current_scope}{" "}
            {t("excluded · catalog drift")}{" "}
            {snapshot.catalog_invariant.missing_definitions.length ||
            snapshot.catalog_invariant.orphan_definitions.length
              ? t("detected")
              : t("none")}
            .
          </span>
        )}
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        {gates.map((gate) => (
          <GateCard key={gate.gate_id} gate={gate} t={t} />
        ))}
      </section>
    </div>
  );
}
