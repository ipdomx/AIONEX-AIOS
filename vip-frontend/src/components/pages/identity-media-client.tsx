"use client";

import {
  CircleAlert,
  Download,
  Film,
  LoaderCircle,
  Mic2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Upload,
  UserCheck,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  createIdentityMediaExecution,
  downloadIdentityMediaExecution,
  getIdentityMediaCapabilities,
  getIdentityMediaRequests,
  listIdentityMediaExecutions,
  requestIdentityMediaAccess,
  type IdentityBasis,
  type IdentityMediaAccessRequest,
  type IdentityMediaCapabilities,
  type IdentityMediaExecution,
  type IdentityMediaOperation,
} from "@/lib/identity-media-api";

const terminal = new Set(["completed", "failed", "cancelled", "blocked", "needs_review"]);
const inputClass =
  "glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";

const operations: Array<{ id: IdentityMediaOperation; icon: typeof Mic2 }> = [
  { id: "voice_clone", icon: Mic2 },
  { id: "talking_head", icon: Film },
  { id: "avatar_generation", icon: Sparkles },
  { id: "face_reenactment", icon: Film },
  { id: "lip_sync", icon: Film },
  { id: "voice_transform", icon: Mic2 },
  { id: "face_swap", icon: Film },
];

function newKey(operation: string) {
  const id = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `identity-media-${operation}-${id}`;
}

function statusClass(status: string) {
  if (status === "completed") return "text-emerald-300";
  if (["failed", "cancelled", "blocked", "needs_review"].includes(status)) return "text-rose-300";
  return "text-amber-300";
}

export function IdentityMediaClient() {
  const t = useTranslations("identityMedia");
  const locale = useLocale();
  const [capabilities, setCapabilities] = useState<IdentityMediaCapabilities | null>(null);
  const [requests, setRequests] = useState<IdentityMediaAccessRequest[]>([]);
  const [executions, setExecutions] = useState<IdentityMediaExecution[]>([]);
  const [operation, setOperation] = useState<IdentityMediaOperation>("talking_head");
  const [basis, setBasis] = useState<IdentityBasis>("fictional_inspired");
  const [subject, setSubject] = useState("Original AIONEX persona");
  const [script, setScript] = useState(t("defaultScript"));
  const [reason, setReason] = useState("");
  const [sourceImage, setSourceImage] = useState<File | null>(null);
  const [sourceAudio, setSourceAudio] = useState<File | null>(null);
  const [sourceVideo, setSourceVideo] = useState<File | null>(null);
  const [rightsEvidence, setRightsEvidence] = useState<File | null>(null);
  const [selfAttestation, setSelfAttestation] = useState(false);
  const [disclosure, setDisclosure] = useState(false);
  const [commercialRequested, setCommercialRequested] = useState(false);
  const [commercialAuthorized, setCommercialAuthorized] = useState(false);
  const [costAuthorization, setCostAuthorization] = useState("5.00");
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(t("loading"));

  const selectedCapability = useMemo(
    () => capabilities?.operations.find((item) => item.operation === operation) ?? null,
    [capabilities, operation],
  );
  const realPerson = basis !== "fictional_inspired";
  const licensedFigure = basis === "licensed_public_figure";
  const ownerOverride = selectedCapability?.owner_override;
  const ownerGrantMatches = useMemo(() => {
    if (!realPerson || !ownerOverride?.allowed) return !realPerson;
    if (!ownerOverride.identity_bases.includes(basis as Exclude<IdentityBasis, "fictional_inspired">)) return false;
    if (ownerOverride.subject_scope === "any") return true;
    return Boolean(subject.trim()) && ownerOverride.subject_reference?.trim().toLocaleLowerCase() === subject.trim().toLocaleLowerCase();
  }, [basis, ownerOverride, realPerson, subject]);
  const runtimeReady = Boolean(selectedCapability?.runtime_ready && capabilities?.worker_live && capabilities?.provider_configured);
  const canExecute = runtimeReady && !licensedFigure && ownerGrantMatches;
  const pendingRequest = requests.find(
    (item) =>
      item.review_status === "pending" &&
      item.operation === operation &&
      item.identity_basis === basis &&
      item.subject_reference.trim().toLocaleLowerCase() === subject.trim().toLocaleLowerCase(),
  );
  const activeExecutions = executions.some((item) => !terminal.has(item.status));

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [caps, access, jobs] = await Promise.all([
        getIdentityMediaCapabilities(),
        getIdentityMediaRequests(),
        listIdentityMediaExecutions(),
      ]);
      setCapabilities(caps);
      setRequests(access.requests);
      setExecutions(jobs.executions);
      if (!quiet) setMessage(t("synced"));
    } catch (error) {
      if (!quiet) setMessage(error instanceof Error ? error.message : t("loadError"));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!activeExecutions) return;
    const timer = window.setInterval(() => void load(true), 4000);
    return () => window.clearInterval(timer);
  }, [activeExecutions, load]);

  useEffect(() => {
    setSourceImage(null);
    setSourceAudio(null);
    setSourceVideo(null);
    setRightsEvidence(null);
    setSelfAttestation(false);
    setDisclosure(false);
  }, [operation, basis]);

  async function requestApproval() {
    if (!realPerson || !subject.trim()) {
      setMessage(t("subjectRequired"));
      return;
    }
    setBusy("approval");
    try {
      await requestIdentityMediaAccess({
        operation,
        identity_basis: basis as Exclude<IdentityBasis, "fictional_inspired">,
        subject_reference: subject.trim(),
        reason: reason.trim(),
      });
      setMessage(t("approvalRequested"));
      await load(true);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("approvalError"));
    } finally {
      setBusy(null);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canExecute) {
      setMessage(licensedFigure ? t("licensedPending") : realPerson ? t("ownerRequired") : t("runtimePending"));
      return;
    }
    if (!subject.trim()) {
      setMessage(t("subjectRequired"));
      return;
    }
    if (!disclosure) {
      setMessage(t("disclosureRequired"));
      return;
    }
    if (basis === "self" && !selfAttestation) {
      setMessage(t("selfAttestationRequired"));
      return;
    }
    if (basis === "consented_person" && !rightsEvidence) {
      setMessage(t("consentFileRequired"));
      return;
    }
    if (commercialRequested && !commercialAuthorized) {
      setMessage(t("commercialRequired"));
      return;
    }
    const maximum = Number(costAuthorization);
    if (!Number.isFinite(maximum) || maximum <= 0 || maximum > 25) {
      setMessage(t("costInvalid"));
      return;
    }
    setBusy("execute");
    try {
      const body = new FormData();
      body.set("operation", operation);
      body.set("identity_basis", basis);
      body.set("subject_reference", subject.trim());
      body.set("idempotency_key", newKey(operation));
      body.set("synthetic_media_disclosure_accepted", "true");
      body.set("approved_max_cost_usd", String(maximum));
      body.set("script", script.trim());
      body.set("estimated_duration_seconds", "10");
      body.set("rights_attestation_accepted", String(basis === "self" && selfAttestation));
      body.set("commercial_use_requested", String(commercialRequested));
      body.set("commercial_use_authorized", String(commercialAuthorized));
      body.set("claims_real_identity", String(realPerson));
      if (realPerson) body.set("named_real_person_reference", subject.trim());
      if (sourceImage) body.set("source_image", sourceImage);
      if (sourceAudio) body.set("source_audio", sourceAudio);
      if (sourceVideo) body.set("source_video", sourceVideo);
      if (rightsEvidence) body.set("rights_evidence_file", rightsEvidence);
      const created = await createIdentityMediaExecution(body);
      setExecutions((current) => [created, ...current.filter((item) => item.execution_id !== created.execution_id)]);
      setMessage(t("queued"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("executionError"));
    } finally {
      setBusy(null);
    }
  }

  async function download(item: IdentityMediaExecution) {
    setBusy(`download:${item.execution_id}`);
    try {
      const { blob, filename } = await downloadIdentityMediaExecution(item.execution_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage(t("downloadStarted"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("downloadError"));
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <section className="page-shell py-16 text-white"><div className="glass-panel flex min-h-52 items-center justify-center rounded-3xl"><LoaderCircle className="h-7 w-7 animate-spin text-electric-200" /></div></section>;
  }

  return (
    <section className="page-shell space-y-6 py-10 text-white sm:py-14">
      <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
        <div className="max-w-3xl">
          <span className="eyebrow"><Sparkles className="h-3.5 w-3.5" /> {t("eyebrow")}</span>
          <h1 className="section-title mt-6">{t("title")}</h1>
          <p className="section-copy mt-4">{t("description")}</p>
        </div>
        <div className="flex gap-2">
          <Link href={`/${locale}/studio`} className="btn-secondary">{t("backStudio")}</Link>
          <button className="btn-secondary" onClick={() => void load()} disabled={busy !== null}><RefreshCw className="h-4 w-4" /> {t("refresh")}</button>
        </div>
      </div>

      <div className="glass-panel rounded-3xl p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-electric-200" />
          <div><p className="font-semibold">{t("policyTitle")}</p><p className="mt-1 text-xs leading-6 text-white/45">{t("policyCopy")}</p></div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {operations.map(({ id, icon: Icon }) => {
          const cap = capabilities?.operations.find((item) => item.operation === id);
          return (
            <button key={id} type="button" onClick={() => setOperation(id)} className={`glass-panel rounded-2xl p-4 text-start transition ${operation === id ? "ring-1 ring-electric-300/60" : "opacity-80 hover:opacity-100"}`}>
              <Icon className="h-5 w-5 text-electric-200" />
              <div className="mt-3 font-semibold">{t(`operation.${id}`)}</div>
              <div className={`mt-2 text-[11px] ${cap?.runtime_ready ? "text-emerald-300" : "text-amber-300"}`}>{cap?.runtime_ready ? t("runtimeReady") : t("runtimePending")}</div>
            </button>
          );
        })}
      </div>

      <form onSubmit={submit} className="glass-panel space-y-5 rounded-3xl p-5 sm:p-6">
        <div className="grid gap-4 lg:grid-cols-2">
          <label className="space-y-2 text-xs text-white/55">{t("identityBasis")}
            <select className={inputClass} value={basis} onChange={(event) => setBasis(event.target.value as IdentityBasis)}>
              <option value="fictional_inspired">{t("basis.fictional_inspired")}</option>
              <option value="self">{t("basis.self")}</option>
              <option value="consented_person">{t("basis.consented_person")}</option>
              <option value="licensed_public_figure">{t("basis.licensed_public_figure")}</option>
            </select>
          </label>
          <label className="space-y-2 text-xs text-white/55">{t("subject")}
            <input className={inputClass} value={subject} onChange={(event) => setSubject(event.target.value)} placeholder={t("subjectPlaceholder")} />
          </label>
        </div>

        {realPerson && (
          <div className={`rounded-2xl border p-4 ${ownerGrantMatches ? "border-emerald-500/20 bg-emerald-500/5" : "border-amber-500/20 bg-amber-500/5"}`}>
            <div className="flex items-start gap-3">
              {ownerGrantMatches ? <UserCheck className="mt-0.5 h-5 w-5 text-emerald-300" /> : <CircleAlert className="mt-0.5 h-5 w-5 text-amber-300" />}
              <div className="min-w-0 flex-1">
                <div className="font-semibold">{licensedFigure ? t("licensedTitle") : ownerGrantMatches ? t("ownerGranted") : t("ownerRequired")}</div>
                <p className="mt-1 text-xs leading-6 text-white/45">{licensedFigure ? t("licensedPending") : ownerGrantMatches ? t("ownerGrantedCopy") : t("ownerRequiredCopy")}</p>
                {!ownerGrantMatches && !pendingRequest && (
                  <div className="mt-3 space-y-3">
                    <textarea className={inputClass} value={reason} onChange={(event) => setReason(event.target.value)} placeholder={t("requestReason")} />
                    <button type="button" className="btn-primary" disabled={busy !== null || !subject.trim()} onClick={() => void requestApproval()}>{t("requestApproval")}</button>
                  </div>
                )}
                {pendingRequest && <div className="mt-3 inline-flex rounded-full border border-amber-500/20 px-3 py-1 text-xs text-amber-200">{t("approvalPending")}</div>}
              </div>
            </div>
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-2">
          {(operation === "face_reenactment" || operation === "talking_head" || operation === "avatar_generation") && (
            <label className="space-y-2 text-xs text-white/55"><Upload className="inline h-4 w-4" /> {t("sourceImage")}<input className={inputClass} type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setSourceImage(event.target.files?.[0] || null)} /></label>
          )}
          {(operation === "voice_clone" || operation === "lip_sync" || operation === "face_reenactment" || operation === "talking_head" || operation === "avatar_generation") && (
            <label className="space-y-2 text-xs text-white/55"><Upload className="inline h-4 w-4" /> {t(operation === "voice_clone" || operation === "lip_sync" ? "sourceAudioRequired" : "sourceAudioOptional")}<input className={inputClass} type="file" accept="audio/wav,audio/mpeg,audio/mp4" onChange={(event) => setSourceAudio(event.target.files?.[0] || null)} /></label>
          )}
          {operation === "lip_sync" && (
            <label className="space-y-2 text-xs text-white/55"><Upload className="inline h-4 w-4" /> {t("sourceVideo")}<input className={inputClass} type="file" accept="video/mp4" onChange={(event) => setSourceVideo(event.target.files?.[0] || null)} /></label>
          )}
          {operation !== "lip_sync" && operation !== "face_swap" && operation !== "voice_transform" && (
            <label className="space-y-2 text-xs text-white/55 lg:col-span-2">{t("script")}<textarea className={`${inputClass} min-h-28`} value={script} onChange={(event) => setScript(event.target.value)} /></label>
          )}
        </div>

        {basis === "self" && ownerGrantMatches && (
          <label className="flex items-start gap-3 rounded-2xl border border-white/[0.08] p-4 text-xs leading-6 text-white/55">
            <input className="mt-1" type="checkbox" checked={selfAttestation} onChange={(event) => setSelfAttestation(event.target.checked)} />
            <span>{t("selfAttestation")}</span>
          </label>
        )}
        {basis === "consented_person" && ownerGrantMatches && (
          <label className="space-y-2 text-xs text-white/55"><Upload className="inline h-4 w-4" /> {t("consentEvidence")}<input className={inputClass} type="file" accept="application/pdf,image/png,image/jpeg,text/plain" onChange={(event) => setRightsEvidence(event.target.files?.[0] || null)} /></label>
        )}

        <div className="grid gap-3 lg:grid-cols-2">
          <label className="flex items-start gap-3 rounded-2xl border border-white/[0.08] p-4 text-xs leading-6 text-white/55"><input className="mt-1" type="checkbox" checked={disclosure} onChange={(event) => setDisclosure(event.target.checked)} /><span>{t("disclosure")}</span></label>
          <label className="flex items-start gap-3 rounded-2xl border border-white/[0.08] p-4 text-xs leading-6 text-white/55"><input className="mt-1" type="checkbox" checked={commercialRequested} onChange={(event) => setCommercialRequested(event.target.checked)} /><span>{t("commercialRequested")}</span></label>
          {commercialRequested && <label className="flex items-start gap-3 rounded-2xl border border-white/[0.08] p-4 text-xs leading-6 text-white/55"><input className="mt-1" type="checkbox" checked={commercialAuthorized} onChange={(event) => setCommercialAuthorized(event.target.checked)} /><span>{t("commercialAuthorized")}</span></label>}
          <label className="space-y-2 text-xs text-white/55">{t("costAuthorization")}<input className={inputClass} type="number" min="0.01" max="25" step="0.01" value={costAuthorization} onChange={(event) => setCostAuthorization(event.target.value)} /><span className="block text-[11px] text-white/35">{t("costAuthorizationCopy")}</span></label>
        </div>

        <button className="btn-primary" type="submit" disabled={busy !== null || !canExecute}>
          {busy === "execute" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} {canExecute ? t("generate") : licensedFigure ? t("licensedUnavailable") : realPerson ? t("ownerGate") : t("runtimePending")}
        </button>
      </form>

      <section className="glass-panel rounded-3xl p-5 sm:p-6">
        <div className="flex items-center justify-between gap-4"><div><h2 className="font-semibold">{t("recentTitle")}</h2><p className="mt-1 text-xs text-white/40">{t("recentCopy")}</p></div><div className="text-xs text-electric-200">{message}</div></div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs text-white/55">
            <thead className="text-white/30"><tr><th className="py-2">{t("operationLabel")}</th><th>{t("basisLabel")}</th><th>{t("status")}</th><th>{t("provider")}</th><th>{t("cost")}</th><th>{t("output")}</th></tr></thead>
            <tbody>
              {executions.map((item) => (
                <tr key={item.execution_id} className="border-t border-white/[0.06]"><td className="py-3">{t(`operation.${item.operation}`)}</td><td>{t(`basis.${item.identity_basis}`)}</td><td className={statusClass(item.status)}>{item.status}</td><td>{item.provider} · {item.model}</td><td>{item.actual_cost_usd == null ? t("costUnknown") : `$${item.actual_cost_usd.toFixed(4)}`}</td><td>{item.output_ready ? <button className="text-electric-200 hover:text-white" disabled={busy !== null} onClick={() => void download(item)}><Download className="inline h-4 w-4" /> {t("download")}</button> : "—"}</td></tr>
              ))}
              {!executions.length && <tr><td colSpan={6} className="py-8 text-center text-white/30">{t("noExecutions")}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
