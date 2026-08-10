"use client";

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  StopCircle,
  Wrench,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  cancelSecurityScan,
  createSecurityScan,
  getSecurityLabAccess,
  listSecurityFindings,
  listSecurityRemediations,
  listSecurityScans,
  listSecurityTargets,
  listSecurityTools,
  registerExternalSecurityTarget,
  verifyExternalSecurityTarget,
} from "@/lib/api";
import type {
  SecurityFindingRecord,
  SecurityLabAccess,
  SecurityProfile,
  SecurityRemediationRecord,
  SecurityScanRecord,
  SecurityTargetRecord,
  SecurityTool,
} from "@/types";

type VerificationState = {
  targetId: string;
  path: string;
  challenge: string;
} | null;

export function SecurityLabClient() {
  const t = useTranslations("securityLab");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [access, setAccess] = useState<SecurityLabAccess | null>(null);
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
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError("");
    try {
      const accessData = await getSecurityLabAccess();
      setAccess(accessData);
      if (!accessData.enabled || !accessData.granted) {
        setTargets([]);
        setScans([]);
        setTools([]);
        setRemediations([]);
        setFindings([]);
        return;
      }
      const [targetData, scanData, toolData, remediationData] =
        await Promise.all([
          listSecurityTargets(),
          listSecurityScans(),
          listSecurityTools(),
          listSecurityRemediations(),
        ]);
      setTargets(targetData);
      setScans(scanData);
      setTools(toolData);
      setRemediations(remediationData);
      const firstVerified = targetData.find(
        (item) => item.authorization_status === "verified",
      );
      setTargetId((current) => current || firstVerified?.id || "");
      setProfile((current) =>
        accessData.profiles.includes(current)
          ? current
          : (accessData.profiles[0] ?? "passive"),
      );
      const completed = scanData.find((item) => item.status === "completed");
      setSelectedScanId((current) => current || completed?.id || "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedScanId || !access?.granted || !access.enabled) {
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
  }, [access, selectedScanId]);

  const availableTools = useMemo(
    () => tools.filter((item) => item.available).length,
    [tools],
  );
  const activeScans = useMemo(
    () => scans.filter((item) => ["queued", "running"].includes(item.status)).length,
    [scans],
  );
  const verifiedTargets = useMemo(
    () => targets.filter((item) => item.authorization_status === "verified"),
    [targets],
  );

  async function startScan() {
    if (!targetId) return;
    setBusy(true);
    setError("");
    try {
      const created = await createSecurityScan(targetId, profile);
      setMessage(t("scanQueued", { id: created.id.slice(0, 8) }));
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("scanError"));
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
      setError(cause instanceof Error ? cause.message : t("cancelError"));
    } finally {
      setBusy(false);
    }
  }

  async function registerExternal() {
    if (!externalOrigin.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await registerExternalSecurityTarget(externalOrigin.trim());
      setVerification({
        targetId: result.id,
        path: result.verification.path,
        challenge: result.verification.challenge,
      });
      setMessage(t("verificationCreated"));
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("targetError"));
    } finally {
      setBusy(false);
    }
  }

  async function verifyExternal() {
    if (!verification) return;
    setBusy(true);
    setError("");
    try {
      await verifyExternalSecurityTarget(
        verification.targetId,
        verification.challenge,
      );
      setVerification(null);
      setExternalOrigin("");
      setMessage(t("verificationPassed"));
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("verificationError"));
    } finally {
      setBusy(false);
    }
  }

  if (isLoading || (!isAuthenticated && !error)) {
    return (
      <section className="section-pad">
        <div className="page-shell flex min-h-[45vh] items-center justify-center">
          <LoaderCircle className="h-8 w-8 animate-spin text-electric-200" />
        </div>
      </section>
    );
  }

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

        {!access?.enabled || !access.granted ? (
          <Card>
            <CardContent>
              <ShieldCheck className="h-6 w-6 text-electric-200" />
              <h2 className="mt-5 text-xl font-semibold">{t("ownerControlled")}</h2>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-white/50">
                {t("ownerControlledCopy")}
              </p>
            </CardContent>
          </Card>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Metric icon={ShieldCheck} label={t("accessLevel")} value={access.level || "—"} />
              <Metric icon={Wrench} label={t("availableEngines")} value={String(availableTools)} />
              <Metric icon={Activity} label={t("activeScans")} value={String(activeScans)} />
              <Metric icon={CheckCircle2} label={t("verifiedTargets")} value={String(verifiedTargets.length)} />
            </div>

            <Card>
              <CardContent>
                <div className="flex items-center gap-2">
                  <Play className="h-5 w-5 text-electric-200" />
                  <h2 className="text-xl font-semibold">{t("startValidation")}</h2>
                </div>
                <p className="mt-2 text-sm leading-7 text-white/45">
                  {t("startValidationCopy")}
                </p>
                <div className="mt-6 grid gap-4 lg:grid-cols-2">
                  <label className="text-sm text-white/60">
                    {t("target")}
                    <select
                      value={targetId}
                      onChange={(event) => setTargetId(event.target.value)}
                      className="mt-2 h-12 w-full rounded-xl border border-white/10 bg-ink-950 px-3 text-white outline-none focus:border-electric-300/40"
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
                      className="mt-2 h-12 w-full rounded-xl border border-white/10 bg-ink-950 px-3 text-white outline-none focus:border-electric-300/40"
                    >
                      {access.profiles.map((item) => (
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

            <Card>
              <CardContent>
                <div className="flex items-center gap-2">
                  <ExternalLink className="h-5 w-5 text-electric-200" />
                  <h2 className="text-xl font-semibold">{t("externalTarget")}</h2>
                </div>
                <p className="mt-2 text-sm leading-7 text-white/45">
                  {t("externalTargetCopy")}
                </p>
                <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                  <input
                    type="url"
                    value={externalOrigin}
                    onChange={(event) => setExternalOrigin(event.target.value)}
                    placeholder="https://example.com"
                    className="h-12 flex-1 rounded-xl border border-white/10 bg-black/20 px-4 text-sm text-white outline-none placeholder:text-white/25 focus:border-electric-300/40"
                  />
                  <Button
                    variant="secondary"
                    disabled={busy || !externalOrigin.trim()}
                    onClick={() => void registerExternal()}
                  >
                    {t("createVerification")}
                  </Button>
                </div>
                {verification && (
                  <div className="mt-5 rounded-2xl border border-electric-300/15 bg-electric-500/[0.06] p-4 text-sm">
                    <p className="font-semibold text-white">{t("verificationStep")}</p>
                    <p className="mt-2 break-all text-white/55">
                      {verification.path}
                    </p>
                    <code className="mt-3 block overflow-x-auto rounded-lg bg-black/25 p-3 text-xs text-electric-100">
                      {verification.challenge}
                    </code>
                    <p className="mt-3 text-xs leading-6 text-white/40">
                      {t("verificationCopy")}
                    </p>
                    <Button
                      className="mt-4"
                      disabled={busy}
                      onClick={() => void verifyExternal()}
                    >
                      {t("verifyNow")}
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <h2 className="text-xl font-semibold">{t("recentScans")}</h2>
                <div className="mt-5 overflow-x-auto">
                  <table className="w-full min-w-[800px] text-start text-sm">
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
                        const active = ["queued", "running"].includes(scan.status);
                        return (
                          <tr key={scan.id} className="text-white/60">
                            <td className="p-2">{target?.origin ?? scan.target_id.slice(0, 8)}</td>
                            <td className="p-2">{t(`profiles.${scan.profile}`)}</td>
                            <td className="p-2">{scan.status}</td>
                            <td className="p-2">{scan.summary.finding_count ?? "—"}</td>
                            <td className="p-2">
                              C {severity.critical ?? 0} · H {severity.high ?? 0} · M {severity.medium ?? 0}
                            </td>
                            <td className="p-2">
                              <div className="flex gap-2">
                                {scan.status === "completed" && (
                                  <button
                                    type="button"
                                    className="text-electric-200 hover:text-electric-100"
                                    onClick={() => setSelectedScanId(scan.id)}
                                  >
                                    {t("view")}
                                  </button>
                                )}
                                {active && (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    className="inline-flex items-center gap-1 text-red-200 hover:text-red-100 disabled:opacity-50"
                                    onClick={() => void cancelScan(scan.id)}
                                  >
                                    <StopCircle className="h-3.5 w-3.5" />
                                    {t("cancel")}
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <h2 className="text-xl font-semibold">{t("selectedFindings")}</h2>
                {!selectedScanId ? (
                  <p className="mt-4 text-sm text-white/40">{t("selectCompletedScan")}</p>
                ) : findings.length ? (
                  <div className="mt-5 space-y-3">
                    {findings.slice(0, 100).map((finding) => (
                      <div
                        key={finding.id}
                        className="rounded-2xl border border-white/[0.07] bg-black/15 p-4"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <AlertTriangle className="h-4 w-4 text-amber-200" />
                          <span className="font-semibold text-white">{finding.title}</span>
                          <span className="rounded-full border border-white/10 px-2 py-0.5 text-xs uppercase text-white/45">
                            {finding.severity}
                          </span>
                          <span className="text-xs text-white/30">{finding.state}</span>
                        </div>
                        <p className="mt-2 text-xs text-white/40">
                          {finding.source} · {finding.cwe || finding.owasp || finding.category}
                        </p>
                        {finding.remediation && (
                          <p className="mt-3 text-sm leading-6 text-white/50">
                            {finding.remediation}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-white/40">{t("noFindings")}</p>
                )}
              </CardContent>
            </Card>

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

            {remediations.length > 0 && (
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
          </>
        )}
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
        <Icon className="h-5 w-5 text-electric-200" aria-hidden="true" />
        <p className="mt-5 text-xs uppercase tracking-[0.14em] text-white/35">{label}</p>
        <p className="mt-2 break-words text-2xl font-semibold text-white">{value}</p>
      </CardContent>
    </Card>
  );
}
