"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clipboard,
  ClipboardCheck,
  Crown,
  FileText,
  Globe2,
  LoaderCircle,
  Play,
  Printer,
  RefreshCw,
  ShieldCheck,
  StopCircle,
  Trash2,
  Wrench,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  ApiError,
  cancelSecurityScan,
  createSecurityScan,
  getSecurityLabAccess,
  getSecurityScanReport,
  listSecurityFindings,
  listSecurityRemediations,
  listSecurityScans,
  listSecurityTargets,
  listSecurityTools,
  registerExternalSecurityTarget,
  removeSecurityTarget,
  verifyExternalSecurityTarget,
} from "@/lib/api";
import type {
  SecurityFindingRecord,
  SecurityLabAccess,
  SecurityProfile,
  SecurityRemediationRecord,
  SecurityScanRecord,
  SecurityScanReport,
  SecurityTargetRecord,
  SecurityTool,
  SecurityVerificationInstructions,
  SecurityVerificationMethod,
} from "@/types";

type VerificationState = {
  targetId: string;
  origin: string;
  challenge: string;
  instructions: SecurityVerificationInstructions;
} | null;

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;
const ACTIVE_STATES = ["queued", "running"];
const POLL_MS = 6000;

const severityTone: Record<string, string> = {
  critical: "border-crimson-400/40 bg-crimson-500/15 text-crimson-100",
  high: "border-orange-400/35 bg-orange-500/10 text-orange-100",
  medium: "border-amber-400/30 bg-amber-500/10 text-amber-100",
  low: "border-sky-400/25 bg-sky-500/10 text-sky-100",
  info: "border-white/10 bg-white/[0.04] text-white/60",
};

const selectClass =
  "mt-2 h-12 w-full rounded-xl border border-white/10 bg-obsidian-950 px-3 text-white outline-none focus:border-crimson-300/40";

function groupFindings(rows: SecurityFindingRecord[]) {
  const groups: Record<string, SecurityFindingRecord[]> = {};
  for (const severity of SEVERITIES) groups[severity] = [];
  for (const row of rows) {
    const key = SEVERITIES.includes(row.severity as (typeof SEVERITIES)[number])
      ? row.severity
      : "info";
    groups[key].push(row);
  }
  return groups;
}

export function SecurityLabClient() {
  const t = useTranslations("securityLab");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [access, setAccess] = useState<SecurityLabAccess | null>(null);
  const [accessDenied, setAccessDenied] = useState(false);
  const [targets, setTargets] = useState<SecurityTargetRecord[]>([]);
  const [scans, setScans] = useState<SecurityScanRecord[]>([]);
  const [tools, setTools] = useState<SecurityTool[]>([]);
  const [remediations, setRemediations] = useState<SecurityRemediationRecord[]>([]);
  const [findings, setFindings] = useState<SecurityFindingRecord[]>([]);
  const [targetId, setTargetId] = useState("");
  const [profile, setProfile] = useState<SecurityProfile>("passive");
  const [selectedScanId, setSelectedScanId] = useState("");
  const [externalOrigin, setExternalOrigin] = useState("");
  const [verification, setVerification] = useState<VerificationState>(null);
  const [method, setMethod] = useState<SecurityVerificationMethod>("http_file");
  const [copied, setCopied] = useState("");
  const [reportScanId, setReportScanId] = useState("");
  const [report, setReport] = useState<SecurityScanReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const describeError = useCallback(
    (cause: unknown, fallback: string) => {
      if (cause instanceof ApiError && cause.code && t.has(`errors.${cause.code}`)) {
        const detail =
          cause.detail && typeof cause.detail === "object"
            ? (cause.detail as Record<string, unknown>)
            : {};
        return t(`errors.${cause.code}`, {
          allowed: String(detail.allowed ?? ""),
          used: String(detail.used ?? ""),
        });
      }
      return cause instanceof Error ? cause.message : fallback;
    },
    [t],
  );

  const load = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError("");
    try {
      let accessData: SecurityLabAccess;
      try {
        accessData = await getSecurityLabAccess();
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) {
          setAccessDenied(true);
          setAccess(null);
          return;
        }
        throw cause;
      }
      setAccessDenied(false);
      setAccess(accessData);
      const canRead =
        accessData.granted || Boolean(accessData.reports_available);
      if (!accessData.enabled || !canRead) {
        setTargets([]);
        setScans([]);
        setTools([]);
        setRemediations([]);
        setFindings([]);
        return;
      }
      const [targetData, scanData] = await Promise.all([
        listSecurityTargets(),
        listSecurityScans(),
      ]);
      setTargets(targetData);
      setScans(scanData);
      if (accessData.granted) {
        const [toolData, remediationData] = await Promise.all([
          listSecurityTools(),
          listSecurityRemediations().catch(() => [] as SecurityRemediationRecord[]),
        ]);
        setTools(toolData);
        setRemediations(remediationData);
      } else {
        setTools([]);
        setRemediations([]);
      }
      const firstVerified = targetData.find(
        (item) => item.authorization_status === "verified",
      );
      setTargetId((current) =>
        targetData.some((item) => item.id === current && item.authorization_status === "verified")
          ? current
          : firstVerified?.id || "",
      );
      setProfile((current) =>
        accessData.profiles.includes(current)
          ? current
          : (accessData.profiles[0] ?? "passive"),
      );
      const completed = scanData.find((item) => item.status === "completed");
      setSelectedScanId((current) => current || completed?.id || "");
    } catch (cause) {
      setError(describeError(cause, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [describeError, isAuthenticated, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasActiveScan = useMemo(
    () => scans.some((item) => ACTIVE_STATES.includes(item.status)),
    [scans],
  );

  // Progress: poll only while a scan is queued or running.
  useEffect(() => {
    if (!hasActiveScan) return;
    const timer = window.setInterval(() => {
      void listSecurityScans()
        .then(setScans)
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [hasActiveScan]);

  const canReadReports = Boolean(access?.granted || access?.reports_available);

  useEffect(() => {
    if (!selectedScanId || !canReadReports) {
      setFindings([]);
      return;
    }
    let cancelled = false;
    void listSecurityFindings(selectedScanId)
      .then((rows) => {
        if (!cancelled) setFindings(rows);
      })
      .catch(() => {
        if (!cancelled) setFindings([]);
      });
    return () => {
      cancelled = true;
    };
  }, [canReadReports, selectedScanId]);

  useEffect(() => {
    if (!reportScanId) {
      setReport(null);
      return;
    }
    const root = document.documentElement;
    root.setAttribute("data-security-report", "1");
    let cancelled = false;
    void getSecurityScanReport(reportScanId)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(describeError(cause, t("reportError")));
          setReportScanId("");
        }
      });
    return () => {
      cancelled = true;
      root.removeAttribute("data-security-report");
    };
  }, [describeError, reportScanId, t]);

  const availableTools = useMemo(
    () => tools.filter((item) => item.available).length,
    [tools],
  );
  const activeScans = useMemo(
    () => scans.filter((item) => ACTIVE_STATES.includes(item.status)).length,
    [scans],
  );
  const verifiedTargets = useMemo(
    () => targets.filter((item) => item.authorization_status === "verified"),
    [targets],
  );
  const groupedFindings = useMemo(() => groupFindings(findings), [findings]);

  function label(group: string, value: string) {
    const key = `${group}.${value}`;
    return t.has(key) ? t(key) : value;
  }

  async function copyValue(key: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      window.setTimeout(() => setCopied((current) => (current === key ? "" : current)), 2000);
    } catch {
      setCopied("");
    }
  }

  async function startScan() {
    if (!targetId) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const created = await createSecurityScan(targetId, profile);
      setMessage(t("scanQueued", { id: created.id.slice(0, 8) }));
      await load();
    } catch (cause) {
      setError(describeError(cause, t("scanError")));
    } finally {
      setBusy(false);
    }
  }

  async function cancelScan(scanId: string) {
    setBusy(true);
    setError("");
    try {
      await cancelSecurityScan(scanId);
      setMessage(t("scanCancelled"));
      await load();
    } catch (cause) {
      setError(describeError(cause, t("cancelError")));
    } finally {
      setBusy(false);
    }
  }

  async function registerExternal(origin: string) {
    if (!origin.trim()) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await registerExternalSecurityTarget(origin.trim());
      setVerification({
        targetId: result.id,
        origin: result.origin,
        challenge: result.verification.challenge,
        instructions: result.verification,
      });
      const dnsAvailable = result.verification.methods?.dns_txt.available;
      setMethod((current) => (current === "dns_txt" && !dnsAvailable ? "http_file" : current));
      setMessage(t("verificationCreated"));
      await load();
    } catch (cause) {
      setError(describeError(cause, t("targetError")));
    } finally {
      setBusy(false);
    }
  }

  async function verifyExternal() {
    if (!verification) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await verifyExternalSecurityTarget(
        verification.targetId,
        verification.challenge,
        method,
      );
      setVerification(null);
      setExternalOrigin("");
      setMessage(t("verificationPassed"));
      await load();
    } catch (cause) {
      setError(describeError(cause, t("verificationError")));
    } finally {
      setBusy(false);
    }
  }

  async function removeTarget(target: SecurityTargetRecord) {
    if (!window.confirm(t("removeConfirm", { origin: target.origin }))) return;
    setBusy(true);
    setError("");
    try {
      await removeSecurityTarget(target.id);
      if (verification?.targetId === target.id) setVerification(null);
      setMessage(t("siteRemoved"));
      await load();
    } catch (cause) {
      setError(describeError(cause, t("removeError")));
    } finally {
      setBusy(false);
    }
  }

  if (isLoading || (!isAuthenticated && !error)) {
    return (
      <section className="section-pad">
        <div className="page-shell flex min-h-[45vh] items-center justify-center">
          <LoaderCircle className="h-8 w-8 animate-spin text-crimson-200" />
        </div>
      </section>
    );
  }

  if (reportScanId) {
    return (
      <ReportView
        report={report}
        onBack={() => setReportScanId("")}
        label={label}
        locale={locale}
      />
    );
  }

  const upgradeRequired = accessDenied || Boolean(access?.upgrade_required);
  const granted = Boolean(access?.enabled && access.granted);
  const limits = access?.limits ?? null;
  const usage = access?.usage;
  const verificationInfo = verification?.instructions.methods;

  return (
    <section className="section-pad">
      <div className="page-shell space-y-7">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-4xl">
            <span className="eyebrow">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
              {t("eyebrow")}
            </span>
            <h1 className="section-title mt-6">{t("title")}</h1>
            <p className="section-copy mt-4">{t("description")}</p>
          </div>
          <Button
            variant="secondary"
            disabled={loading || busy}
            onClick={() => void load()}
          >
            <RefreshCw
              className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            {t("refresh")}
          </Button>
        </div>

        {message && <StatusMessage tone="success">{message}</StatusMessage>}
        {error && <StatusMessage tone="error">{error}</StatusMessage>}

        {access && !access.enabled ? (
          <Card>
            <CardContent>
              <ShieldCheck className="h-6 w-6 text-crimson-200" />
              <h2 className="mt-5 text-xl font-semibold">{t("ownerControlled")}</h2>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-white/50">
                {t("disabledCopy")}
              </p>
            </CardContent>
          </Card>
        ) : !granted ? (
          upgradeRequired ? (
            <Card className="border border-crimson-400/25">
              <CardContent>
                <Crown className="h-6 w-6 text-crimson-200" aria-hidden="true" />
                <h2 className="mt-5 text-xl font-semibold">{t("upgradeTitle")}</h2>
                <p className="mt-3 max-w-3xl text-sm leading-7 text-white/55">
                  {t("upgradeCopy")}
                </p>
                <ul className="mt-5 grid gap-2 text-sm text-white/60 sm:grid-cols-2">
                  {(["upgradePointVerify", "upgradePointScan", "upgradePointFindings", "upgradePointReport"] as const).map(
                    (key) => (
                      <li key={key} className="flex items-start gap-2">
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-crimson-200" aria-hidden="true" />
                        {t(key)}
                      </li>
                    ),
                  )}
                </ul>
                <Link
                  href={`/${locale}/pricing`}
                  className="mt-6 inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-transparent bg-crimson-500 px-5 text-sm font-semibold text-white transition hover:bg-crimson-400"
                >
                  <Crown className="h-4 w-4" aria-hidden="true" />
                  {t("upgradeCta")}
                </Link>
                {access?.reports_available && (
                  <p className="mt-4 text-xs leading-6 text-white/40">{t("pastReportsCopy")}</p>
                )}
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent>
                <ShieldCheck className="h-6 w-6 text-crimson-200" />
                <h2 className="mt-5 text-xl font-semibold">{t("ownerControlled")}</h2>
                <p className="mt-3 max-w-3xl text-sm leading-7 text-white/50">
                  {t("ownerControlledCopy")}
                </p>
              </CardContent>
            </Card>
          )
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Metric
                icon={ShieldCheck}
                label={access?.source === "subscription" ? t("plan") : t("accessLevel")}
                value={
                  access?.source === "subscription"
                    ? access.plan_code || "—"
                    : access?.level || "—"
                }
              />
              <Metric
                icon={Globe2}
                label={t("verifiedTargets")}
                value={
                  limits
                    ? t("usageOf", {
                        used: String(usage?.verified_targets ?? verifiedTargets.length),
                        max: String(limits.max_verified_targets),
                      })
                    : String(verifiedTargets.length)
                }
              />
              <Metric
                icon={Activity}
                label={t("scansThisMonth")}
                value={
                  limits
                    ? t("usageOf", {
                        used: String(usage?.scans_this_month ?? 0),
                        max: String(limits.max_scans_per_month),
                      })
                    : String(usage?.scans_this_month ?? 0)
                }
              />
              <Metric
                icon={Wrench}
                label={access?.source === "subscription" ? t("activeScans") : t("availableEngines")}
                value={
                  access?.source === "subscription"
                    ? t("usageOf", {
                        used: String(activeScans),
                        max: String(limits?.max_concurrent_scans ?? 1),
                      })
                    : String(availableTools)
                }
              />
            </div>

            <Card>
              <CardContent>
                <div className="flex items-center gap-2">
                  <Globe2 className="h-5 w-5 text-crimson-200" />
                  <h2 className="text-xl font-semibold">{t("yourSites")}</h2>
                </div>
                <p className="mt-2 text-sm leading-7 text-white/45">{t("yourSitesCopy")}</p>
                <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                  <label className="sr-only" htmlFor="security-site-origin">
                    {t("siteUrl")}
                  </label>
                  <input
                    id="security-site-origin"
                    type="url"
                    inputMode="url"
                    value={externalOrigin}
                    onChange={(event) => setExternalOrigin(event.target.value)}
                    placeholder="https://example.com"
                    dir="ltr"
                    className="h-12 flex-1 rounded-xl border border-white/[0.14] bg-obsidian-700 px-4 text-sm text-white outline-none placeholder:text-zinc-500 focus:border-crimson-500"
                  />
                  <Button
                    disabled={busy || !externalOrigin.trim()}
                    onClick={() => void registerExternal(externalOrigin)}
                  >
                    {t("addSite")}
                  </Button>
                </div>

                {verification && (
                  <div className="mt-6 rounded-2xl border border-crimson-400/20 bg-black/20 p-4 sm:p-5">
                    <p className="font-semibold text-white">
                      {t("verifyOwnership", { origin: verification.origin })}
                    </p>
                    <p className="mt-1 text-xs text-white/40">{t("chooseMethod")}</p>
                    <div className="mt-4 inline-flex rounded-xl border border-white/10 bg-obsidian-950 p-1" role="tablist">
                      {(["http_file", "dns_txt"] as const).map((item) => {
                        const disabled =
                          item === "dns_txt" && verificationInfo?.dns_txt.available === false;
                        return (
                          <button
                            key={item}
                            type="button"
                            role="tab"
                            aria-selected={method === item}
                            disabled={disabled}
                            onClick={() => setMethod(item)}
                            className={`rounded-lg px-4 py-2 text-sm font-medium transition disabled:opacity-40 ${
                              method === item
                                ? "bg-crimson-500 text-white"
                                : "text-white/60 hover:text-white"
                            }`}
                          >
                            {item === "http_file" ? t("methodFile") : t("methodDns")}
                          </button>
                        );
                      })}
                    </div>

                    {method === "http_file" ? (
                      <div className="mt-4 space-y-3">
                        <p className="text-sm text-white/55">{t("methodFileCopy")}</p>
                        <CopyField
                          label={t("fileUrl")}
                          value={verificationInfo?.http_file.url ?? verification.origin + verification.instructions.path}
                          copied={copied === "file-url"}
                          onCopy={(value) => void copyValue("file-url", value)}
                          copyLabel={t("copy")}
                          copiedLabel={t("copied")}
                        />
                        <CopyField
                          label={t("fileContent")}
                          value={verification.challenge}
                          copied={copied === "file-content"}
                          onCopy={(value) => void copyValue("file-content", value)}
                          copyLabel={t("copy")}
                          copiedLabel={t("copied")}
                        />
                      </div>
                    ) : verificationInfo?.dns_txt.available && verificationInfo.dns_txt.record_name ? (
                      <div className="mt-4 space-y-3">
                        <p className="text-sm text-white/55">{t("methodDnsCopy")}</p>
                        <CopyField
                          label={t("recordName")}
                          value={verificationInfo.dns_txt.record_name}
                          copied={copied === "dns-name"}
                          onCopy={(value) => void copyValue("dns-name", value)}
                          copyLabel={t("copy")}
                          copiedLabel={t("copied")}
                        />
                        <CopyField
                          label={t("recordType")}
                          value="TXT"
                          copied={copied === "dns-type"}
                          onCopy={(value) => void copyValue("dns-type", value)}
                          copyLabel={t("copy")}
                          copiedLabel={t("copied")}
                        />
                        <CopyField
                          label={t("recordValue")}
                          value={verificationInfo.dns_txt.record_value}
                          copied={copied === "dns-value"}
                          onCopy={(value) => void copyValue("dns-value", value)}
                          copyLabel={t("copy")}
                          copiedLabel={t("copied")}
                        />
                        <p className="text-xs leading-6 text-white/40">{t("dnsPropagation")}</p>
                      </div>
                    ) : (
                      <p className="mt-4 text-sm text-white/55">{t("dnsUnavailable")}</p>
                    )}
                    <p className="mt-4 text-xs leading-6 text-white/40">
                      {t("reverifyNote", {
                        days: String(access?.verification?.reverify_after_days ?? 30),
                      })}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-3">
                      <Button disabled={busy} onClick={() => void verifyExternal()}>
                        {busy ? (
                          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                        ) : (
                          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                        )}
                        {t("verifyNow")}
                      </Button>
                      <Button variant="ghost" disabled={busy} onClick={() => setVerification(null)}>
                        {t("later")}
                      </Button>
                    </div>
                  </div>
                )}

                <div className="mt-6 space-y-3">
                  {targets.length === 0 ? (
                    <p className="text-sm text-white/40">{t("noSites")}</p>
                  ) : (
                    targets.map((target) => {
                      const verified = target.authorization_status === "verified";
                      const external = target.kind === "external_authorized";
                      return (
                        <div
                          key={target.id}
                          className="flex flex-col gap-3 rounded-2xl border border-white/[0.07] bg-black/15 p-4 sm:flex-row sm:items-center sm:justify-between"
                        >
                          <div className="min-w-0">
                            <p className="truncate font-semibold text-white" dir="ltr">
                              {target.origin}
                            </p>
                            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-white/40">
                              <span
                                className={`rounded-full border px-2 py-0.5 ${
                                  verified
                                    ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-100"
                                    : "border-amber-400/25 bg-amber-500/10 text-amber-100"
                                }`}
                              >
                                {label("targetStatus", target.authorization_status)}
                              </span>
                              {verified && (
                                <span>
                                  {label("methods", target.verification_method)}
                                  {target.verified_at
                                    ? ` · ${new Date(target.verified_at).toLocaleDateString(locale)}`
                                    : ""}
                                </span>
                              )}
                            </p>
                          </div>
                          {external && (
                            <div className="flex flex-wrap gap-2">
                              {verified ? (
                                <Button
                                  size="sm"
                                  disabled={busy || hasActiveScan}
                                  onClick={() => setTargetId(target.id)}
                                  variant={targetId === target.id ? "primary" : "secondary"}
                                >
                                  <Play className="h-3.5 w-3.5" aria-hidden="true" />
                                  {t("selectForScan")}
                                </Button>
                              ) : (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  disabled={busy}
                                  onClick={() => void registerExternal(target.origin)}
                                >
                                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                                  {t("newInstructions")}
                                </Button>
                              )}
                              <Button
                                size="sm"
                                variant="danger"
                                disabled={busy}
                                onClick={() => void removeTarget(target)}
                              >
                                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                                {t("remove")}
                              </Button>
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <div className="flex items-center gap-2">
                  <Play className="h-5 w-5 text-crimson-200" />
                  <h2 className="text-xl font-semibold">{t("startValidation")}</h2>
                </div>
                <p className="mt-2 text-sm leading-7 text-white/45">
                  {access?.source === "subscription"
                    ? t("startValidationSubscriberCopy")
                    : t("startValidationCopy")}
                </p>
                <div className="mt-6 grid gap-4 lg:grid-cols-2">
                  <label className="text-sm text-white/60">
                    {t("target")}
                    <select
                      value={targetId}
                      onChange={(event) => setTargetId(event.target.value)}
                      className={selectClass}
                    >
                      <option value="">{t("selectTarget")}</option>
                      {verifiedTargets.map((target) => (
                        <option key={target.id} value={target.id}>
                          {target.origin}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm text-white/60">
                    {t("profile")}
                    <select
                      value={profile}
                      onChange={(event) => setProfile(event.target.value as SecurityProfile)}
                      className={selectClass}
                    >
                      {(access?.profiles ?? []).map((item) => (
                        <option key={item} value={item}>
                          {t(`profiles.${item}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <Button
                  className="mt-5"
                  disabled={busy || !targetId}
                  onClick={() => void startScan()}
                >
                  <Play className="h-4 w-4" />
                  {t("queueValidation")}
                </Button>
              </CardContent>
            </Card>
          </>
        )}

        {(granted || access?.reports_available) && (
          <>
            <Card>
              <CardContent>
                <h2 className="text-xl font-semibold">
                  {granted ? t("recentScans") : t("pastReports")}
                </h2>
                {scans.length === 0 ? (
                  <p className="mt-4 text-sm text-white/40">{t("noScans")}</p>
                ) : (
                  <div className="mt-5 overflow-x-auto">
                    <table className="w-full min-w-[820px] text-start text-sm">
                      <thead className="text-xs text-white/35">
                        <tr>
                          <th className="p-2 text-start">{t("target")}</th>
                          <th className="p-2 text-start">{t("profile")}</th>
                          <th className="p-2 text-start">{t("status")}</th>
                          <th className="p-2 text-start">{t("findings")}</th>
                          <th className="p-2 text-start">{t("severity")}</th>
                          <th className="p-2 text-start">{t("actions")}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.06]">
                        {scans.slice(0, 50).map((scan) => {
                          const target = targets.find((item) => item.id === scan.target_id);
                          const severity = scan.summary.severity ?? {};
                          const active = ACTIVE_STATES.includes(scan.status);
                          return (
                            <tr key={scan.id} className="text-white/60">
                              <td className="p-2" dir="ltr">
                                {target?.origin ?? scan.target_id.slice(0, 8)}
                              </td>
                              <td className="p-2">{t(`profiles.${scan.profile}`)}</td>
                              <td className="p-2">
                                <span className="inline-flex items-center gap-2">
                                  {active && (
                                    <LoaderCircle className="h-3.5 w-3.5 animate-spin text-crimson-200" aria-hidden="true" />
                                  )}
                                  {label("scanStatus", scan.status)}
                                </span>
                                {active && (
                                  <span className="mt-2 block h-1 w-28 overflow-hidden rounded-full bg-white/10" aria-hidden="true">
                                    <span
                                      className={`block h-full rounded-full bg-crimson-500 ${
                                        scan.status === "running" ? "w-2/3 animate-pulse" : "w-1/6"
                                      }`}
                                    />
                                  </span>
                                )}
                              </td>
                              <td className="p-2">{scan.summary.finding_count ?? "—"}</td>
                              <td className="p-2">
                                <span className="flex flex-wrap gap-1">
                                  {(["critical", "high", "medium"] as const).map((key) => (
                                    <span
                                      key={key}
                                      className={`rounded-full border px-2 py-0.5 text-[11px] ${severityTone[key]}`}
                                    >
                                      {label("severities", key)} {severity[key] ?? 0}
                                    </span>
                                  ))}
                                </span>
                              </td>
                              <td className="p-2">
                                <div className="flex flex-wrap gap-3">
                                  {scan.status === "completed" && (
                                    <>
                                      <button
                                        type="button"
                                        className="text-crimson-200 hover:text-crimson-100"
                                        onClick={() => setSelectedScanId(scan.id)}
                                      >
                                        {t("view")}
                                      </button>
                                      <button
                                        type="button"
                                        className="inline-flex items-center gap-1 text-white/60 hover:text-white"
                                        onClick={() => setReportScanId(scan.id)}
                                      >
                                        <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                                        {t("exportReport")}
                                      </button>
                                    </>
                                  )}
                                  {active && (
                                    <button
                                      type="button"
                                      disabled={busy}
                                      className="inline-flex items-center gap-1 text-rose-200 hover:text-rose-100 disabled:opacity-50"
                                      onClick={() => void cancelScan(scan.id)}
                                    >
                                      <StopCircle className="h-3.5 w-3.5" />
                                      {t("cancel")}
                                    </button>
                                  )}
                                </div>
                                {scan.status === "failed" && scan.error_message && (
                                  <p className="mt-1 text-xs text-rose-200/70">{scan.error_message}</p>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-xl font-semibold">{t("selectedFindings")}</h2>
                  {selectedScanId && (
                    <Button size="sm" variant="secondary" onClick={() => setReportScanId(selectedScanId)}>
                      <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                      {t("exportReport")}
                    </Button>
                  )}
                </div>
                {!selectedScanId ? (
                  <p className="mt-4 text-sm text-white/40">{t("selectCompletedScan")}</p>
                ) : findings.length ? (
                  <div className="mt-5 space-y-6">
                    <div className="flex flex-wrap gap-2">
                      {SEVERITIES.map((key) => (
                        <span
                          key={key}
                          className={`rounded-full border px-3 py-1 text-xs ${severityTone[key]}`}
                        >
                          {label("severities", key)} · {groupedFindings[key].length}
                        </span>
                      ))}
                    </div>
                    {SEVERITIES.filter((key) => groupedFindings[key].length > 0).map((key) => (
                      <div key={key}>
                        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-white/50">
                          {label("severities", key)}
                        </h3>
                        <div className="mt-3 space-y-3">
                          {groupedFindings[key].slice(0, 100).map((finding) => (
                            <FindingCard key={finding.id} finding={finding} label={label} />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-white/40">{t("noFindings")}</p>
                )}
              </CardContent>
            </Card>
          </>
        )}

        {granted && access?.source !== "subscription" && tools.length > 0 && (
          <Card>
            <CardContent>
              <h2 className="text-xl font-semibold">{t("engineInventory")}</h2>
              <p className="mt-2 text-sm text-white/45">{t("engineInventoryCopy")}</p>
              <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {tools.map((tool) => (
                  <div
                    key={tool.id}
                    className="rounded-2xl border border-white/[0.07] bg-black/15 p-4"
                  >
                    <p className="font-semibold text-white">{tool.id}</p>
                    <p className="mt-1 text-xs text-white/35">
                      {tool.category} · {tool.available ? t("available") : t("unavailable")}
                    </p>
                    <p className="mt-2 text-xs leading-5 text-white/30">
                      {tool.requires_clone
                        ? t("cloneOnly")
                        : tool.active
                          ? t("authorizedRuntime")
                          : t("sourcePassive")}
                    </p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {granted && remediations.length > 0 && (
          <Card>
            <CardContent>
              <h2 className="text-xl font-semibold">{t("remediations")}</h2>
              <p className="mt-2 text-sm text-white/45">{t("remediationsCopy")}</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {remediations.slice(0, 20).map((item) => (
                  <div key={item.id} className="rounded-xl border border-white/[0.07] p-3 text-sm">
                    <p className="font-medium text-white">{item.status}</p>
                    <p className="mt-1 text-xs text-white/35">{item.finding_id.slice(0, 8)}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </section>
  );
}

function FindingCard({
  finding,
  label,
}: {
  finding: SecurityFindingRecord;
  label: (group: string, value: string) => string;
}) {
  const t = useTranslations("securityLab");
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-black/15 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-200" aria-hidden="true" />
        <span className="font-semibold text-white">{finding.title}</span>
        <span
          className={`rounded-full border px-2 py-0.5 text-xs ${severityTone[finding.severity] ?? severityTone.info}`}
        >
          {label("severities", finding.severity)}
        </span>
        <span className="text-xs text-white/30">{finding.state}</span>
      </div>
      <p className="mt-2 text-xs text-white/40" dir="ltr">
        {finding.source} · {finding.cwe || finding.owasp || finding.category}
        {finding.location ? ` · ${finding.location}` : ""}
      </p>
      <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-crimson-200/80">
          {t("howToFix")}
        </p>
        <p className="mt-2 text-sm leading-6 text-white/55">
          {finding.remediation || t("noRemediation")}
        </p>
      </div>
    </div>
  );
}

function CopyField({
  label,
  value,
  copied,
  onCopy,
  copyLabel,
  copiedLabel,
}: {
  label: string;
  value: string;
  copied: boolean;
  onCopy: (value: string) => void;
  copyLabel: string;
  copiedLabel: string;
}) {
  return (
    <div>
      <p className="text-xs text-white/40">{label}</p>
      <div className="mt-1 flex items-stretch gap-2">
        <code
          dir="ltr"
          className="block flex-1 overflow-x-auto whitespace-nowrap rounded-lg bg-black/30 p-3 text-xs text-crimson-100"
        >
          {value}
        </code>
        <button
          type="button"
          onClick={() => onCopy(value)}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-white/10 px-3 text-xs text-white/70 transition hover:border-crimson-300/40 hover:text-white"
          aria-label={`${copyLabel}: ${label}`}
        >
          {copied ? (
            <ClipboardCheck className="h-3.5 w-3.5 text-emerald-200" aria-hidden="true" />
          ) : (
            <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {copied ? copiedLabel : copyLabel}
        </button>
      </div>
    </div>
  );
}

function ReportView({
  report,
  onBack,
  label,
  locale,
}: {
  report: SecurityScanReport | null;
  onBack: () => void;
  label: (group: string, value: string) => string;
  locale: string;
}) {
  const t = useTranslations("securityLab");
  if (!report) {
    return (
      <section className="section-pad">
        <div className="page-shell flex min-h-[45vh] items-center justify-center gap-3 text-white/60">
          <LoaderCircle className="h-6 w-6 animate-spin text-crimson-200" aria-hidden="true" />
          {t("reportLoading")}
        </div>
      </section>
    );
  }
  const formatDate = (value: string | null | undefined) =>
    value ? new Date(value).toLocaleString(locale) : "—";
  return (
    <section className="section-pad">
      <div className="page-shell security-report space-y-6">
        <div className="security-report-actions flex flex-wrap gap-3">
          <Button variant="secondary" onClick={onBack}>
            <ArrowLeft className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
            {t("backToLab")}
          </Button>
          <Button onClick={() => window.print()}>
            <Printer className="h-4 w-4" aria-hidden="true" />
            {t("printReport")}
          </Button>
        </div>
        <div>
          <span className="eyebrow">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
            {t("eyebrow")}
          </span>
          <h1 className="section-title mt-4">{t("reportTitle")}</h1>
          <dl className="mt-5 grid gap-3 text-sm text-white/60 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-white/35">{t("target")}</dt>
              <dd className="font-semibold text-white" dir="ltr">
                {report.target?.origin ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-white/35">{t("profile")}</dt>
              <dd>{label("profiles", report.scan.profile)}</dd>
            </div>
            <div>
              <dt className="text-xs text-white/35">{t("reportCompleted")}</dt>
              <dd>{formatDate(report.scan.completed_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-white/35">{t("reportGenerated")}</dt>
              <dd>{formatDate(report.generated_at)}</dd>
            </div>
          </dl>
        </div>
        <div className="flex flex-wrap gap-2">
          {SEVERITIES.map((key) => (
            <span key={key} className={`rounded-full border px-3 py-1 text-xs ${severityTone[key]}`}>
              {label("severities", key)} · {report.severity_counts[key] ?? 0}
            </span>
          ))}
        </div>
        {SEVERITIES.every((key) => (report.findings_by_severity[key] ?? []).length === 0) ? (
          <p className="text-sm text-white/50">{t("noFindings")}</p>
        ) : (
          SEVERITIES.filter((key) => (report.findings_by_severity[key] ?? []).length > 0).map((key) => (
            <div key={key} className="break-inside-avoid">
              <h2 className="text-lg font-semibold text-white">{label("severities", key)}</h2>
              <div className="mt-3 space-y-3">
                {(report.findings_by_severity[key] ?? []).map((finding) => (
                  <FindingCard key={finding.id} finding={finding} label={label} />
                ))}
              </div>
            </div>
          ))
        )}
        <p className="text-xs leading-6 text-white/35">{t("reportDisclaimer")}</p>
      </div>
    </section>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof ShieldCheck;
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent>
        <Icon className="h-5 w-5 text-crimson-200" aria-hidden="true" />
        <p className="mt-5 text-xs uppercase tracking-[0.14em] text-white/35">{label}</p>
        <p className="mt-2 break-words text-2xl font-semibold text-white">{value}</p>
      </CardContent>
    </Card>
  );
}
