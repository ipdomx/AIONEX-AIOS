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
  reviewOwnerExternalActivationEvidence,
  submitOwnerExternalActivationEvidence,
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
  satisfied_external_evidence: {
    label: "Satisfied by reviewed external evidence",
    className: "border-cyan-500/20 bg-cyan-500/10 text-cyan-200",
    icon: BadgeCheck,
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
    className: "border-white/10 bg-white/3 text-white/45",
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

function EvidenceWorkflow({
  gate,
  t,
  onChanged,
}: {
  gate: ExternalActivationGate;
  t: (text: string) => string;
  onChanged: () => Promise<void>;
}) {
  const [reference, setReference] = useState("");
  const [sha256, setSha256] = useState("");
  const [issuer, setIssuer] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [notes, setNotes] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const submit = async () => {
    setBusy(true);
    setMessage("");
    try {
      await submitOwnerExternalActivationEvidence(gate.gate_id, {
        evidence_reference: reference.trim(),
        evidence_sha256: sha256.trim().toLowerCase(),
        issuer: issuer.trim(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        notes: notes.trim(),
      });
      setMessage("Evidence submitted for governed review.");
      setReference("");
      setSha256("");
      setIssuer("");
      setExpiresAt("");
      setNotes("");
      await onChanged();
    } catch {
      setMessage("Evidence submission failed validation or authorization.");
    } finally {
      setBusy(false);
    }
  };

  const review = async (decision: "accepted" | "rejected" | "revoked") => {
    setBusy(true);
    setMessage("");
    try {
      await reviewOwnerExternalActivationEvidence(gate.gate_id, {
        decision,
        review_note: reviewNote.trim(),
      });
      setMessage(
        decision === "accepted"
          ? "Evidence review recorded: accepted."
          : decision === "rejected"
            ? "Evidence review recorded: rejected."
            : "Evidence review recorded: revoked.",
      );
      setReviewNote("");
      await onChanged();
    } catch {
      setMessage("Evidence review failed validation or authorization.");
    } finally {
      setBusy(false);
    }
  };

  if (!gate.owner_evidence_reviewable) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/2 p-3 text-xs leading-5 text-white/40">
        {t(
          "Runtime-derived gate. Manual evidence cannot activate or override this boundary.",
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-xl border border-white/8 bg-black/10 p-4">
      <div>
        <div className="text-xs font-semibold text-white/75">
          {t("Governed Owner evidence")}
        </div>
        <p className="mt-1 text-[11px] leading-5 text-white/35">
          {t(
            "Submitting evidence never bypasses runtime gates. Review state, checksum, issuer, version and audit history are retained.",
          )}
        </p>
      </div>

      {gate.owner_evidence && (
        <dl className="grid gap-2 rounded-lg border border-white/6 bg-white/2 p-3 text-[11px] sm:grid-cols-2">
          <div>
            <dt className="text-white/30">{t("Review status")}</dt>
            <dd className="mt-0.5 text-white/70">
              {gate.owner_evidence.review_status}
            </dd>
          </div>
          <div>
            <dt className="text-white/30">{t("Issuer")}</dt>
            <dd className="mt-0.5 wrap-break-word text-white/70">
              {gate.owner_evidence.issuer}
            </dd>
          </div>
          <div>
            <dt className="text-white/30">SHA-256</dt>
            <dd className="mt-0.5 break-all font-mono text-white/55">
              {gate.owner_evidence.evidence_sha256}
            </dd>
          </div>
          <div>
            <dt className="text-white/30">{t("Version")}</dt>
            <dd className="mt-0.5 text-white/70">
              {gate.owner_evidence.version}
            </dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-white/30">{t("Evidence reference")}</dt>
            <dd className="mt-0.5 break-all text-white/55">
              {gate.owner_evidence.evidence_reference}
            </dd>
          </div>
        </dl>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <input
          className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-hidden focus:border-electric-400/50"
          placeholder={t("Evidence reference / vault URI")}
          value={reference}
          onChange={(event) => setReference(event.target.value)}
          maxLength={500}
        />
        <input
          className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 font-mono text-xs text-white outline-hidden focus:border-electric-400/50"
          placeholder="SHA-256"
          value={sha256}
          onChange={(event) => setSha256(event.target.value)}
          maxLength={64}
        />
        <input
          className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-hidden focus:border-electric-400/50"
          placeholder={t("Issuer / authority")}
          value={issuer}
          onChange={(event) => setIssuer(event.target.value)}
          maxLength={200}
        />
        <input
          className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-hidden focus:border-electric-400/50"
          type="datetime-local"
          aria-label={t("Evidence expiry")}
          value={expiresAt}
          onChange={(event) => setExpiresAt(event.target.value)}
        />
      </div>
      <textarea
        className="min-h-20 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-hidden focus:border-electric-400/50"
        placeholder={t("Evidence notes")}
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
        maxLength={2000}
      />
      <button
        type="button"
        className="btn-secondary"
        disabled={
          busy ||
          !reference.trim() ||
          sha256.trim().length !== 64 ||
          !issuer.trim()
        }
        onClick={() => void submit()}
      >
        {t("Submit evidence")}
      </button>

      {gate.owner_evidence && (
        <div className="space-y-3 border-t border-white/6 pt-4">
          <textarea
            className="min-h-16 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-hidden focus:border-electric-400/50"
            placeholder={t("Review note")}
            value={reviewNote}
            onChange={(event) => setReviewNote(event.target.value)}
            maxLength={2000}
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => void review("accepted")}
            >
              {t("Accept evidence")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => void review("rejected")}
            >
              {t("Reject")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => void review("revoked")}
            >
              {t("Revoke")}
            </button>
          </div>
        </div>
      )}

      {message && (
        <div className="text-[11px] text-electric-200/80">{t(message)}</div>
      )}
    </div>
  );
}

function GateCard({
  gate,
  t,
  onChanged,
}: {
  gate: ExternalActivationGate;
  t: (text: string) => string;
  onChanged: () => Promise<void>;
}) {
  const meta = statusMeta[gate.status];
  const StatusIcon = meta.icon;
  const liveEntries = Object.entries(gate.live_evidence);

  return (
    <article className="glass-card space-y-5 p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="wrap-break-word text-base font-semibold text-white">
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
                <dd className="mt-0.5 wrap-break-word text-xs text-white/65">
                  {evidenceValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <EvidenceWorkflow gate={gate} t={t} onChanged={onChanged} />

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
        "External activation ledger synchronized with governed runtime and external evidence.",
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setMessage("External activation ledger could not be loaded.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  const reload = useCallback(async () => {
    await load();
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const gates = useMemo(() => snapshot?.gates ?? [], [snapshot?.gates]);
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
                  "Governed evidence workflow. Runtime gates remain runtime-derived and cannot be manually overridden. Reviewable legal, rights and certification gates accept checksum-bound external evidence with audit history. Store publication and direct Apple Pay remain excluded from the current closeout scope by Owner decision.",
                )}
              </p>
            </div>
          </div>
          <button
            type="button"
            className="btn-secondary"
            disabled={loading}
            onClick={() => void reload()}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("Refresh")}
          </button>
        </div>
      </header>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
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
          <div className="text-3xl font-bold text-cyan-200">
            {snapshot?.counts.satisfied_external_evidence ?? 0}
          </div>
          <div className="mt-1 text-xs text-white/40">
            {t("Satisfied by reviewed evidence")}
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
          <GateCard key={gate.gate_id} gate={gate} t={t} onChanged={reload} />
        ))}
      </section>
    </div>
  );
}
