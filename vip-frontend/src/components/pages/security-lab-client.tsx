"use client";

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  Square,
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
  cancelSecurityLabScan,
  createSecurityLabScan,
  getSecurityLabAccess,
  listProjects,
  listSecurityLabFindings,
  listSecurityLabRemediations,
  listSecurityLabScans,
  listSecurityLabTargets,
  listSecurityLabTools,
  registerSecurityLabManagedTarget,
  requestSecurityLabRemediation,
} from "@/lib/api";
import type {
  Project,
  SecurityFinding,
  SecurityLabAccess,
  SecurityProfile,
  SecurityRemediation,
  SecurityScan,
  SecurityTarget,
  SecurityTool,
} from "@/types";

function severityClass(value: string): string {
  if (value === "critical") return "bg-red-500/15 text-red-200";
  if (value === "high") return "bg-orange-500/15 text-orange-200";
  if (value === "medium") return "bg-amber-500/15 text-amber-100";
  return "bg-white/[0.06] text-white/50";
}

export function SecurityLabClient() {
  const t = useTranslations("securityLab");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [access, setAccess] = useState<SecurityLabAccess | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [targets, setTargets] = useState<SecurityTarget[]>([]);
  const [scans, setScans] = useState<SecurityScan[]>([]);
  const [tools, setTools] = useState<SecurityTool[]>([]);
  const [remediations, setRemediations] = useState<SecurityRemediation[]>([]);
  const [findings, setFindings] = useState<SecurityFinding[]>([]);
  const [selectedProject, setSelectedProject] = useState("");
  const [origin, setOrigin] = useState("");
  const [environment, setEnvironment] = useState<"production" | "staging">(
    "production",
  );
  const [targetId, setTargetId] = useState("");
  const [profile, setProfile] = useState<SecurityProfile>("passive");
  const [selectedScan, setSelectedScan] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const accessData = await getSecurityLabAccess();
      setAccess(accessData);
      if (!accessData.granted || !accessData.enabled) {
        setProjects([]);
        setTargets([]);
        setScans([]);
        setTools([]);
        setRemediations([]);
        setFindings([]);
        return;
      }
      const [projectRows, targetRows, scanRows, toolRows, remediationRows] =
        await Promise.all([
          listProjects(),
          listSecurityLabTargets(),
          listSecurityLabScans(),
          listSecurityLabTools(),
          listSecurityLabRemediations(),
        ]);
      setProjects(projectRows);
      setTargets(targetRows);
      setScans(scanRows);
      setTools(toolRows);
      setRemediations(remediationRows);
      if (!selectedProject && projectRows.length)
        setSelectedProject(projectRows[0].id);
      if (!targetId && targetRows.length) setTargetId(targetRows[0].id);
      const firstCompleted = scanRows.find(
        (item) => item.status === "completed",
      );
      const nextScan = selectedScan || firstCompleted?.id || "";
      setSelectedScan(nextScan);
      if (!accessData.profiles.includes(profile))
        setProfile(accessData.profiles[0] ?? "passive");
      if (nextScan) setFindings(await listSecurityLabFindings(nextScan));
      else setFindings([]);
    } catch {
      setError(t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [profile, selectedProject, selectedScan, t, targetId]);

  useEffect(() => {
    if (isAuthenticated) void load();
    // The callback intentionally snapshots selection state for the first load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated]);

  const availableTools = useMemo(
    () => tools.filter((item) => item.available).length,
    [tools],
  );
  const activeScans = useMemo(
    () => scans.filter((item) => ["queued", "running"].includes(item.status)),
    [scans],
  );
  const selectedScanRecord = scans.find((item) => item.id === selectedScan);

  async function registerTarget() {
    if (!selectedProject || !origin.trim()) return;
    setBusy(true);
    setError("");
    try {
      const target = await registerSecurityLabManagedTarget({
        project_id: selectedProject,
        origin: origin.trim(),
        environment,
      });
      setTargetId(target.id);
      setOrigin("");
      setNotice(t("targetRegistered"));
      await load();
    } catch {
      setError(t("targetError"));
    } finally {
      setBusy(false);
    }
  }

  async function startScan() {
    if (!targetId) return;
    setBusy(true);
    setError("");
    try {
      const created = await createSecurityLabScan(targetId, profile);
      setSelectedScan(created.id);
      setNotice(t("scanQueued"));
      await load();
    } catch (value) {
      setError(value instanceof Error ? value.message : t("scanError"));
    } finally {
      setBusy(false);
    }
  }

  async function cancelScan(scanId: string) {
    setBusy(true);
    setError("");
    try {
      await cancelSecurityLabScan(scanId);
      setNotice(t("scanCancelled"));
      await load();
    } catch {
      setError(t("scanError"));
    } finally {
      setBusy(false);
    }
  }

  async function selectScan(scanId: string) {
    setSelectedScan(scanId);
    setBusy(true);
    setError("");
    try {
      setFindings(await listSecurityLabFindings(scanId));
    } catch {
      setError(t("findingsError"));
    } finally {
      setBusy(false);
    }
  }

  async function remediate(findingId: string) {
    setBusy(true);
    setError("");
    try {
      await requestSecurityLabRemediation(findingId);
      setRemediations(await listSecurityLabRemediations());
      setNotice(t("remediationQueued"));
    } catch (value) {
      setError(value instanceof Error ? value.message : t("remediationError"));
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
      <div className="page-shell">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <span className="eyebrow">{t("eyebrow")}</span>
            <h1 className="section-title mt-6">{t("title")}</h1>
            <p className="section-copy mt-4 max-w-4xl">{t("description")}</p>
          </div>
          <Button
            variant="secondary"
            onClick={() => void load()}
            disabled={loading || busy}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("refresh")}
          </Button>
        </div>

        {error && (
          <StatusMessage tone="error" className="mt-6">
            {error}
          </StatusMessage>
        )}
        {notice && !error && (
          <StatusMessage tone="success" className="mt-6">
            {notice}
          </StatusMessage>
        )}

        {!access?.granted || !access.enabled ? (
          <Card className="mt-8">
            <CardContent>
              <div className="flex items-start gap-4">
                <ShieldCheck className="mt-1 h-6 w-6 text-electric-200" />
                <div>
                  <h2 className="text-xl font-semibold">
                    {t("ownerControlled")}
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-white/45">
                    {t("ownerControlledCopy")}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        ) : (
          <>
            <div className="mt-8 grid gap-4 md:grid-cols-3">
              <Card>
                <CardContent>
                  <ShieldCheck className="h-5 w-5 text-electric-200" />
                  <p className="mt-4 text-2xl font-semibold">{access.level}</p>
                  <p className="mt-1 text-xs text-white/40">{t("level")}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent>
                  <Wrench className="h-5 w-5 text-electric-200" />
                  <p className="mt-4 text-2xl font-semibold">
                    {availableTools}
                  </p>
                  <p className="mt-1 text-xs text-white/40">{t("engines")}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent>
                  <Activity className="h-5 w-5 text-electric-200" />
                  <p className="mt-4 text-2xl font-semibold">
                    {activeScans.length}
                  </p>
                  <p className="mt-1 text-xs text-white/40">
                    {t("activeScans")}
                  </p>
                </CardContent>
              </Card>
            </div>

            <div className="mt-6 grid gap-6 xl:grid-cols-2">
              <Card>
                <CardContent>
                  <h2 className="text-xl font-semibold">
                    {t("registerTarget")}
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-white/40">
                    {t("registerTargetCopy")}
                  </p>
                  <div className="mt-5 space-y-3">
                    <label className="block text-xs text-white/45">
                      {t("project")}
                      <select
                        className="mt-1 w-full rounded-xl border border-white/10 bg-black/25 p-3 text-white"
                        value={selectedProject}
                        onChange={(event) =>
                          setSelectedProject(event.target.value)
                        }
                      >
                        <option value="">{t("selectProject")}</option>
                        {projects.map((project) => (
                          <option key={project.id} value={project.id}>
                            {project.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block text-xs text-white/45">
                      {t("origin")}
                      <input
                        className="mt-1 w-full rounded-xl border border-white/10 bg-black/25 p-3 text-white"
                        value={origin}
                        onChange={(event) => setOrigin(event.target.value)}
                        placeholder="https://project.vip-e.net"
                      />
                    </label>
                    <label className="block text-xs text-white/45">
                      {t("environment")}
                      <select
                        className="mt-1 w-full rounded-xl border border-white/10 bg-black/25 p-3 text-white"
                        value={environment}
                        onChange={(event) =>
                          setEnvironment(
                            event.target.value as "production" | "staging",
                          )
                        }
                      >
                        <option value="production">{t("production")}</option>
                        <option value="staging">{t("staging")}</option>
                      </select>
                    </label>
                    <Button
                      onClick={() => void registerTarget()}
                      disabled={busy || !selectedProject || !origin.trim()}
                    >
                      {t("register")}
                    </Button>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent>
                  <h2 className="text-xl font-semibold">{t("startScan")}</h2>
                  <p className="mt-2 text-sm leading-6 text-white/40">
                    {t("startScanCopy")}
                  </p>
                  <div className="mt-5 space-y-3">
                    <label className="block text-xs text-white/45">
                      {t("target")}
                      <select
                        className="mt-1 w-full rounded-xl border border-white/10 bg-black/25 p-3 text-white"
                        value={targetId}
                        onChange={(event) => setTargetId(event.target.value)}
                      >
                        <option value="">{t("selectTarget")}</option>
                        {targets
                          .filter(
                            (item) => item.authorization_status === "verified",
                          )
                          .map((target) => (
                            <option key={target.id} value={target.id}>
                              {target.origin}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className="block text-xs text-white/45">
                      {t("profile")}
                      <select
                        className="mt-1 w-full rounded-xl border border-white/10 bg-black/25 p-3 text-white"
                        value={profile}
                        onChange={(event) =>
                          setProfile(event.target.value as SecurityProfile)
                        }
                      >
                        {access.profiles.map((item) => (
                          <option key={item} value={item}>
                            {t(`profiles.${item}`)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <Button
                      onClick={() => void startScan()}
                      disabled={busy || !targetId}
                    >
                      <Play className="h-4 w-4" />
                      {t("queue")}
                    </Button>
                    {access.deep_validation_requires_clone && (
                      <p className="text-xs leading-5 text-amber-200/70">
                        {t("cloneNote")}
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card className="mt-6">
              <CardContent>
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <h2 className="text-xl font-semibold">
                      {t("recentScans")}
                    </h2>
                    <p className="mt-2 text-sm text-white/40">
                      {t("recentScansCopy")}
                    </p>
                  </div>
                  {activeScans.length > 0 && (
                    <span className="rounded-full bg-amber-400/10 px-3 py-1 text-xs text-amber-200">
                      {t("runningCount", { count: activeScans.length })}
                    </span>
                  )}
                </div>
                <div className="mt-5 overflow-x-auto">
                  <table className="w-full min-w-[820px] text-start text-xs">
                    <thead className="text-white/35">
                      <tr>
                        <th className="p-2">{t("target")}</th>
                        <th className="p-2">{t("profile")}</th>
                        <th className="p-2">{t("status")}</th>
                        <th className="p-2">{t("findings")}</th>
                        <th className="p-2">{t("severity")}</th>
                        <th className="p-2">{t("actions")}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.06]">
                      {scans.map((scan) => {
                        const target = targets.find(
                          (item) => item.id === scan.target_id,
                        );
                        const severity = scan.summary.severity ?? {};
                        return (
                          <tr key={scan.id} className="text-white/60">
                            <td className="p-2">
                              {target?.origin ?? scan.target_id.slice(0, 8)}
                            </td>
                            <td className="p-2">
                              {t(`profiles.${scan.profile}`)}
                            </td>
                            <td className="p-2">{scan.status}</td>
                            <td className="p-2">
                              {scan.summary.finding_count ?? "—"}
                            </td>
                            <td className="p-2">
                              C {severity.critical ?? 0} · H{" "}
                              {severity.high ?? 0} · M {severity.medium ?? 0}
                            </td>
                            <td className="p-2">
                              <div className="flex gap-2">
                                {scan.status === "completed" && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => void selectScan(scan.id)}
                                    disabled={busy}
                                  >
                                    {t("viewFindings")}
                                  </Button>
                                )}
                                {["queued", "running"].includes(
                                  scan.status,
                                ) && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => void cancelScan(scan.id)}
                                    disabled={busy}
                                  >
                                    <Square className="h-3.5 w-3.5" />
                                    {t("cancel")}
                                  </Button>
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

            {selectedScanRecord && (
              <Card className="mt-6">
                <CardContent>
                  <h2 className="text-xl font-semibold">
                    {t("findingsTitle")}
                  </h2>
                  <p className="mt-2 text-sm text-white/40">
                    {t("findingsCopy")}
                  </p>
                  <div className="mt-5 space-y-3">
                    {findings.length ? (
                      findings.map((finding) => {
                        const canRemediate =
                          access.level === "autonomous" &&
                          finding.state === "confirmed";
                        return (
                          <article
                            key={finding.id}
                            className="rounded-2xl border border-white/[0.07] bg-black/15 p-4"
                          >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <div className="flex flex-wrap items-center gap-2">
                                  <span
                                    className={`rounded-full px-2.5 py-1 text-[11px] uppercase ${severityClass(finding.severity)}`}
                                  >
                                    {finding.severity}
                                  </span>
                                  <span className="text-[11px] text-white/35">
                                    {finding.source}
                                  </span>
                                  <span className="text-[11px] text-white/35">
                                    {Math.round(finding.confidence * 100)}%
                                  </span>
                                </div>
                                <h3 className="mt-3 font-semibold text-white">
                                  {finding.title}
                                </h3>
                                <p className="mt-2 text-xs text-white/40">
                                  {finding.location || finding.category} ·{" "}
                                  {finding.state}
                                </p>
                                {finding.remediation && (
                                  <p className="mt-3 text-sm leading-6 text-white/55">
                                    {finding.remediation}
                                  </p>
                                )}
                              </div>
                              {canRemediate && (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  disabled={busy}
                                  onClick={() => void remediate(finding.id)}
                                >
                                  <Wrench className="h-4 w-4" />
                                  {t("remediate")}
                                </Button>
                              )}
                            </div>
                          </article>
                        );
                      })
                    ) : (
                      <div className="rounded-2xl border border-dashed border-white/10 px-6 py-10 text-center text-sm text-white/40">
                        <CheckCircle2 className="mx-auto h-7 w-7 text-emerald-300/70" />
                        <p className="mt-3">{t("noFindings")}</p>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="mt-6 grid gap-6 xl:grid-cols-2">
              <Card>
                <CardContent>
                  <h2 className="text-xl font-semibold">{t("enginesTitle")}</h2>
                  <div className="mt-4 grid gap-2 sm:grid-cols-2">
                    {tools.map((tool) => (
                      <div
                        key={tool.id}
                        className="rounded-xl border border-white/[0.06] bg-black/15 p-3"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-white">
                            {tool.id}
                          </span>
                          <span
                            className={
                              tool.available
                                ? "text-emerald-300"
                                : "text-white/30"
                            }
                          >
                            {tool.available ? "●" : "○"}
                          </span>
                        </div>
                        <p className="mt-1 text-[11px] text-white/35">
                          {tool.category} ·{" "}
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

              <Card>
                <CardContent>
                  <h2 className="text-xl font-semibold">{t("remediations")}</h2>
                  <p className="mt-2 text-sm text-white/40">
                    {t("remediationsCopy")}
                  </p>
                  <div className="mt-4 space-y-2">
                    {remediations.length ? (
                      remediations.slice(0, 20).map((item) => (
                        <div
                          key={item.id}
                          className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-black/15 p-3 text-xs"
                        >
                          <span className="text-white/60">
                            {item.finding_id.slice(0, 8)}
                          </span>
                          <span className="text-white/40">{item.status}</span>
                        </div>
                      ))
                    ) : (
                      <div className="flex items-center gap-2 text-sm text-white/35">
                        <AlertTriangle className="h-4 w-4" />
                        {t("noRemediations")}
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
