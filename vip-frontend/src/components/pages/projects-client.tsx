"use client";

import {
  ArrowUpRight,
  BadgeCheck,
  BrainCircuit,
  CircleDollarSign,
  Download,
  FolderKanban,
  GraduationCap,
  Landmark,
  Gauge,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Tags,
  Timer,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { ThreeDProjectPanel } from "@/components/pages/three-d-project-panel";
import { useAuth } from "@/hooks/use-auth";
import {
  approveProjectExecution,
  createProject,
  downloadProjectExecution,
  getFreeTierStatus,
  listProjectExecutions,
  listProjects,
  listWorkspaces,
  startProjectExecution,
} from "@/lib/api";
import type {
  FreeTierStatus,
  Project,
  ProjectExecution,
  Workspace,
} from "@/types";

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

function latestExecutionMap(
  pairs: ReadonlyArray<readonly [string, ProjectExecution | null]>,
): Record<string, ProjectExecution | null> {
  return Object.fromEntries(pairs);
}

export function ProjectsClient() {
  const t = useTranslations("projects");
  const locale = useLocale();
  const router = useRouter();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [executions, setExecutions] = useState<
    Record<string, ProjectExecution | null>
  >({});
  const [quota, setQuota] = useState<FreeTierStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [executionError, setExecutionError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [startingProjectId, setStartingProjectId] = useState<string | null>(
    null,
  );
  const [downloadingExecutionId, setDownloadingExecutionId] = useState<
    string | null
  >(null);
  const [approvingExecutionId, setApprovingExecutionId] = useState<
    string | null
  >(null);
  const [createError, setCreateError] = useState("");

  const canCreate = useMemo(
    () =>
      Boolean(
        user?.permissions.includes("projects:write") ||
        user?.permissions.includes("*"),
      ),
    [user],
  );

  const activeProjectIds = useMemo(
    () =>
      Object.entries(executions)
        .filter(([, execution]) =>
          execution ? ["queued", "running"].includes(execution.status) : false,
        )
        .map(([projectId]) => projectId),
    [executions],
  );

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const fetchLatestExecutions = useCallback(async (items: Project[]) => {
    const pairs = await Promise.all(
      items.map(async (project): Promise<[string, ProjectExecution | null]> => {
        try {
          const rows = await listProjectExecutions(project.id, 1);
          return [project.id, rows[0] || null];
        } catch {
          return [project.id, null];
        }
      }),
    );
    return latestExecutionMap(pairs);
  }, []);

  const load = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError("");
    try {
      const [nextProjects, nextWorkspaces, nextQuota] = await Promise.all([
        listProjects(),
        listWorkspaces(),
        getFreeTierStatus(),
      ]);
      const nextExecutions = await fetchLatestExecutions(nextProjects);
      setProjects(nextProjects);
      setWorkspaces(nextWorkspaces);
      setQuota(nextQuota);
      setExecutions(nextExecutions);
    } catch (cause) {
      setError(errorText(cause, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [fetchLatestExecutions, isAuthenticated, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!activeProjectIds.length) return;
    const interval = window.setInterval(() => {
      void Promise.all(
        activeProjectIds.map(async (projectId) => {
          const rows = await listProjectExecutions(projectId, 1);
          return [projectId, rows[0] || null] as const;
        }),
      )
        .then((pairs) => {
          setExecutions((current) => ({
            ...current,
            ...latestExecutionMap([...pairs]),
          }));
          if (
            pairs.some(([, execution]) => execution?.status === "completed")
          ) {
            void listProjects()
              .then(setProjects)
              .catch(() => undefined);
            void getFreeTierStatus()
              .then(setQuota)
              .catch(() => undefined);
          }
        })
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [activeProjectIds]);

  async function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    setCreateError("");
    const form = new FormData(formElement);
    setCreating(true);
    try {
      const project = await createProject({
        name: String(form.get("name") || "").trim(),
        description: String(form.get("description") || "").trim() || null,
        priority: String(form.get("priority") || "medium") as
          "low" | "medium" | "high" | "critical",
        workspace_id: String(form.get("workspaceId") || ""),
        tags: String(form.get("tags") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
          .slice(0, 12),
      });
      setProjects((current) => [project, ...current]);
      setExecutions((current) => ({ ...current, [project.id]: null }));
      setShowCreate(false);
      formElement.reset();
      void getFreeTierStatus()
        .then(setQuota)
        .catch(() => undefined);
    } catch (cause) {
      setCreateError(errorText(cause, t("createError")));
    } finally {
      setCreating(false);
    }
  }

  async function startExecution(project: Project) {
    setExecutionError("");
    const confirmed = window.confirm(
      t("execution.confirm", {
        provider: "AIOS provider-neutral runtime",
        budget: "0.00",
      }),
    );
    if (!confirmed) return;
    setStartingProjectId(project.id);
    try {
      const execution = await startProjectExecution(project.id);
      setExecutions((current) => ({
        ...current,
        [project.id]: execution,
      }));
      setProjects((current) =>
        current.map((item) =>
          item.id === project.id
            ? {
                ...item,
                status: "planning",
                progress: Math.max(item.progress, 1),
              }
            : item,
        ),
      );
      void getFreeTierStatus()
        .then(setQuota)
        .catch(() => undefined);
    } catch (cause) {
      setExecutionError(errorText(cause, t("execution.startError")));
    } finally {
      setStartingProjectId(null);
    }
  }

  async function approveExecution(projectId: string, executionId: string) {
    const confirmed = window.confirm(t("execution.approvalConfirm"));
    if (!confirmed) return;
    setExecutionError("");
    setApprovingExecutionId(executionId);
    try {
      const approved = await approveProjectExecution(projectId, executionId);
      setExecutions((current) => ({ ...current, [projectId]: approved }));
      setProjects((current) =>
        current.map((project) =>
          project.id === projectId
            ? { ...project, status: "completed", progress: 100 }
            : project,
        ),
      );
    } catch (cause) {
      setExecutionError(errorText(cause, t("execution.approvalError")));
    } finally {
      setApprovingExecutionId(null);
    }
  }

  async function downloadExecution(projectId: string, executionId: string) {
    setExecutionError("");
    setDownloadingExecutionId(executionId);
    try {
      const { blob, filename } = await downloadProjectExecution(
        projectId,
        executionId,
      );
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (cause) {
      setExecutionError(errorText(cause, t("execution.downloadError")));
    } finally {
      setDownloadingExecutionId(null);
    }
  }

  function statusLabel(status: string) {
    const known = [
      "planning",
      "active",
      "in_progress",
      "completed",
      "paused",
      "cancelled",
    ];
    return known.includes(status) ? t(`status.${status}`) : status;
  }

  function priorityLabel(priority: string) {
    const known = ["low", "medium", "high", "critical"];
    return known.includes(priority) ? t(`priorityValue.${priority}`) : priority;
  }

  function executionStatusLabel(status: string) {
    const known = ["queued", "running", "completed", "failed"];
    return known.includes(status) ? t(`execution.status.${status}`) : status;
  }

  function executionStageLabel(stage: string) {
    const known = [
      "queued",
      "intake",
      "cognitive_review",
      "constitutional_review",
      "wisdom_deliberation",
      "government_review",
      "provider_model_validation",
      "external_research",
      "provider_execution",
      "provider_execution_completed",
      "implementation_specification",
      "implementation_generation",
      "implementation_tests",
      "rollback_verification",
      "research_verification",
      "ministry_routing",
      "workforce_execution",
      "engineering_review",
      "security_review",
      "integration_review",
      "release_review",
      "review",
      "completed",
      "approved",
      "rework_required",
      "failed",
    ];
    return known.includes(stage) ? t(`execution.stage.${stage}`) : stage;
  }

  if (isLoading || (loading && !projects.length)) {
    return (
      <div className="page-shell section-pad flex items-center justify-center gap-3 text-white/50">
        <LoaderCircle className="h-5 w-5 animate-spin" />
        {t("loading")}
      </div>
    );
  }

  return (
    <section className="section-pad">
      <div className="page-shell">
        <div className="flex flex-col gap-7 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <span className="eyebrow">
              <FolderKanban className="h-3.5 w-3.5" />
              {t("eyebrow")}
            </span>
            <h1 className="section-title mt-7">{t("title")}</h1>
            <p className="section-copy mt-5">{t("description")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCw
                className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
              />
              {t("refresh")}
            </Button>
            {canCreate && (
              <Button
                onClick={() => setShowCreate((current) => !current)}
                disabled={!workspaces.length}
              >
                <Plus className="h-4 w-4" />
                {t("newProject")}
              </Button>
            )}
          </div>
        </div>

        {quota?.free_tier && quota.limits && quota.usage && quota.remaining && (
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs text-white/35">{t("quota.projects")}</p>
              <p className="mt-2 text-2xl font-semibold">
                {quota.usage.projects} / {quota.limits.projects}
              </p>
            </div>
            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs text-white/35">{t("quota.messages")}</p>
              <p className="mt-2 text-2xl font-semibold">
                {quota.remaining.user_messages}
              </p>
            </div>
            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs text-white/35">{t("quota.responses")}</p>
              <p className="mt-2 text-2xl font-semibold">
                {quota.remaining.assistant_responses}
              </p>
            </div>
          </div>
        )}

        {error && (
          <StatusMessage tone="error" className="mt-8">
            {error}
          </StatusMessage>
        )}
        {executionError && (
          <StatusMessage tone="error" className="mt-8">
            {executionError}
          </StatusMessage>
        )}
        {!workspaces.length && !error && (
          <StatusMessage className="mt-8">{t("noWorkspace")}</StatusMessage>
        )}

        {showCreate && (
          <form
            onSubmit={submitProject}
            className="glass-panel mt-8 rounded-3xl p-6 sm:p-8"
          >
            <div className="flex items-center gap-3">
              <Plus className="h-5 w-5 text-electric-200" />
              <h2 className="text-xl font-semibold">{t("createTitle")}</h2>
            </div>
            <div className="mt-7 grid gap-5 sm:grid-cols-2">
              <div>
                <label htmlFor="project-name" className="field-label">
                  {t("name")}
                </label>
                <input
                  id="project-name"
                  name="name"
                  className="field-control"
                  minLength={2}
                  maxLength={160}
                  required
                />
              </div>
              <div>
                <label htmlFor="project-workspace" className="field-label">
                  {t("workspace")}
                </label>
                <select
                  id="project-workspace"
                  name="workspaceId"
                  className="field-control"
                  required
                  defaultValue={workspaces[0]?.id || ""}
                >
                  {workspaces.map((workspace) => (
                    <option
                      key={workspace.id}
                      value={workspace.id}
                      className="bg-ink-800"
                    >
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="project-priority" className="field-label">
                  {t("priority")}
                </label>
                <select
                  id="project-priority"
                  name="priority"
                  className="field-control"
                  defaultValue="medium"
                >
                  {(["low", "medium", "high", "critical"] as const).map(
                    (value) => (
                      <option key={value} value={value} className="bg-ink-800">
                        {t(`priorityValue.${value}`)}
                      </option>
                    ),
                  )}
                </select>
              </div>
              <div>
                <label htmlFor="project-tags" className="field-label">
                  {t("tags")}
                </label>
                <input
                  id="project-tags"
                  name="tags"
                  className="field-control"
                  maxLength={300}
                />
                <p className="mt-2 text-xs text-white/30">{t("tagsRule")}</p>
              </div>
              <div className="sm:col-span-2">
                <label htmlFor="project-description" className="field-label">
                  {t("projectDescription")}
                </label>
                <textarea
                  id="project-description"
                  name="description"
                  className="field-control min-h-32 resize-y"
                  maxLength={2000}
                />
              </div>
            </div>
            {createError && (
              <StatusMessage tone="error" className="mt-5">
                {createError}
              </StatusMessage>
            )}
            <div className="mt-7 flex flex-wrap gap-3">
              <Button type="submit" disabled={creating}>
                {creating ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                {creating ? t("creating") : t("create")}
              </Button>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                {t("cancel")}
              </Button>
            </div>
          </form>
        )}

        <div className="mt-10 grid gap-5 lg:grid-cols-2">
          {projects.map((project) => {
            const execution = executions[project.id];
            const active = Boolean(
              execution && ["queued", "running"].includes(execution.status),
            );
            const ownerApprovalPending = Boolean(
              execution?.status === "completed" &&
              execution.approved !== true &&
              user?.role === "Owner" &&
              execution.result?.blocking_findings?.length === 1 &&
              execution.result.blocking_findings[0] ===
                "owner approval is required",
            );
            return (
              <article
                key={project.id}
                className="glass-panel rounded-3xl p-6 sm:p-8"
              >
                <div className="flex items-start justify-between gap-5">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-electric-200">
                      {statusLabel(project.status)}
                    </p>
                    <h2 className="mt-3 text-xl font-semibold">
                      {project.name}
                    </h2>
                  </div>
                  <span className="rounded-lg border border-white/[0.07] px-2.5 py-1 text-xs text-white/40">
                    {priorityLabel(project.priority)}
                  </span>
                </div>
                {project.description && (
                  <p className="mt-4 line-clamp-3 text-sm leading-7 text-white/50">
                    {project.description}
                  </p>
                )}
                <div
                  className="mt-6 h-1.5 overflow-hidden rounded-full bg-white/[0.06]"
                  aria-label={t("progress", { value: project.progress })}
                >
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-electric-400 to-violet-500"
                    style={{
                      width: `${Math.max(0, Math.min(100, project.progress))}%`,
                    }}
                  />
                </div>
                <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs text-white/35">
                  <span className="inline-flex items-center gap-1.5">
                    <Gauge className="h-3.5 w-3.5" />
                    {project.progress}%
                  </span>
                  <span>{project.workspace}</span>
                  <span>{t("tasks", { count: project.task_count })}</span>
                </div>
                {project.tags.length > 0 && (
                  <div className="mt-5 flex flex-wrap items-center gap-2">
                    <Tags className="h-3.5 w-3.5 text-white/25" />
                    {project.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-md bg-white/[0.05] px-2 py-1 text-[11px] text-white/40"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                <div className="mt-7 rounded-2xl border border-electric-300/10 bg-electric-300/[0.035] p-5">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <BrainCircuit className="h-4 w-4 text-electric-200" />
                      <p className="text-sm font-semibold">
                        {t("execution.title")}
                      </p>
                    </div>
                    {execution && (
                      <span className="rounded-full border border-white/[0.08] px-3 py-1 text-[11px] text-white/45">
                        {executionStatusLabel(execution.status)}
                      </span>
                    )}
                  </div>

                  {!execution ? (
                    <>
                      <p className="mt-3 text-xs leading-6 text-white/40">
                        {t("execution.description")}
                      </p>
                      {canCreate && (
                        <Button
                          className="mt-5"
                          onClick={() => void startExecution(project)}
                          disabled={startingProjectId === project.id}
                        >
                          {startingProjectId === project.id ? (
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                          ) : (
                            <BrainCircuit className="h-4 w-4" />
                          )}
                          {startingProjectId === project.id
                            ? t("execution.starting")
                            : t("execution.start")}
                        </Button>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-violet-500"
                          style={{
                            width: `${Math.max(0, Math.min(100, execution.progress))}%`,
                          }}
                        />
                      </div>
                      <div className="mt-4 grid gap-3 sm:grid-cols-3">
                        <div className="rounded-xl bg-black/10 p-3">
                          <p className="text-[11px] text-white/30">
                            {t("execution.stageLabel")}
                          </p>
                          <p className="mt-1 text-xs text-white/60">
                            {executionStageLabel(execution.stage)}
                          </p>
                        </div>
                        <div className="rounded-xl bg-black/10 p-3">
                          <p className="text-[11px] text-white/30">
                            {t("execution.cost")}
                          </p>
                          <p className="mt-1 inline-flex items-center gap-1 text-xs text-white/60">
                            <CircleDollarSign className="h-3.5 w-3.5" />
                            {(execution.calculated_cost_usd || 0).toFixed(
                              6,
                            )}{" "}
                            USD
                          </p>
                        </div>
                        <div className="rounded-xl bg-black/10 p-3">
                          <p className="text-[11px] text-white/30">
                            {t("execution.readiness")}
                          </p>
                          <p className="mt-1 inline-flex items-center gap-1 text-xs text-white/60">
                            <ShieldCheck className="h-3.5 w-3.5" />
                            {execution.readiness_score == null
                              ? "—"
                              : `${Math.round(execution.readiness_score * 100)}%`}
                          </p>
                        </div>
                      </div>
                      {active && (
                        <p className="mt-4 inline-flex items-center gap-2 text-xs text-white/35">
                          <Timer className="h-3.5 w-3.5" />
                          {t("execution.runningNotice")}
                        </p>
                      )}
                      {execution.status === "completed" && execution.result && (
                        <div className="mt-4 space-y-4 text-xs leading-6 text-white/45">
                          <div>
                            <p>
                              {execution.approved
                                ? t("execution.approved")
                                : t("execution.rework", {
                                    count:
                                      execution.result.blocking_findings
                                        ?.length || 0,
                                  })}
                            </p>
                            <p className="mt-1">
                              {t("execution.usage", {
                                requests: execution.requests_count,
                                tokens: execution.total_tokens,
                              })}
                            </p>
                          </div>

                          <div className="grid gap-3 sm:grid-cols-3">
                            <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                              <p className="flex items-center gap-2 text-white/65">
                                <Landmark className="h-3.5 w-3.5 text-electric-200" />
                                {t("execution.governanceTitle")}
                              </p>
                              <p className="mt-1 text-white/35">
                                {execution.result.all_governance_layers_executed
                                  ? t("execution.governanceComplete")
                                  : t("execution.governancePending")}
                              </p>
                            </div>
                            <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                              <p className="flex items-center gap-2 text-white/65">
                                <Search className="h-3.5 w-3.5 text-electric-200" />
                                {t("execution.researchTitle")}
                              </p>
                              <p className="mt-1 text-white/35">
                                {t("execution.researchSummary", {
                                  sources:
                                    execution.result.external_research?.sources
                                      ?.length || 0,
                                  facts:
                                    execution.result.external_research
                                      ?.verified_facts?.length || 0,
                                })}
                              </p>
                            </div>
                            <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                              <p className="flex items-center gap-2 text-white/65">
                                <GraduationCap className="h-3.5 w-3.5 text-electric-200" />
                                {t("execution.workforceTitle")}
                              </p>
                              <p className="mt-1 text-white/35">
                                {t("execution.workforceSummary", {
                                  count:
                                    execution.result.workforce?.length || 0,
                                  training:
                                    execution.result.workforce?.filter(
                                      (worker) =>
                                        worker.employment_state ===
                                          "retraining" ||
                                        worker.employment_state ===
                                          "supervised",
                                    ).length || 0,
                                })}
                              </p>
                            </div>
                          </div>

                          {ownerApprovalPending && (
                            <StatusMessage>
                              {t("execution.ownerApprovalRequired")}
                            </StatusMessage>
                          )}
                          {execution.result.owner_approval?.approved && (
                            <StatusMessage tone="success">
                              {t("execution.ownerApproved")}
                            </StatusMessage>
                          )}

                          <div className="flex flex-wrap gap-2">
                            {ownerApprovalPending && (
                              <Button
                                onClick={() =>
                                  void approveExecution(
                                    project.id,
                                    execution.id,
                                  )
                                }
                                disabled={approvingExecutionId === execution.id}
                              >
                                {approvingExecutionId === execution.id ? (
                                  <LoaderCircle className="h-4 w-4 animate-spin" />
                                ) : (
                                  <BadgeCheck className="h-4 w-4" />
                                )}
                                {approvingExecutionId === execution.id
                                  ? t("execution.approving")
                                  : t("execution.approve")}
                              </Button>
                            )}
                            {execution.evidence_available && (
                              <Button
                                variant="secondary"
                                onClick={() =>
                                  void downloadExecution(
                                    project.id,
                                    execution.id,
                                  )
                                }
                                disabled={
                                  downloadingExecutionId === execution.id
                                }
                              >
                                {downloadingExecutionId === execution.id ? (
                                  <LoaderCircle className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Download className="h-4 w-4" />
                                )}
                                {t("execution.download")}
                              </Button>
                            )}
                            {canCreate && (
                              <Button
                                variant="ghost"
                                onClick={() => void startExecution(project)}
                                disabled={startingProjectId === project.id}
                              >
                                {startingProjectId === project.id ? (
                                  <LoaderCircle className="h-4 w-4 animate-spin" />
                                ) : (
                                  <RefreshCw className="h-4 w-4" />
                                )}
                                {t("execution.newCycle")}
                              </Button>
                            )}
                          </div>
                        </div>
                      )}
                      {execution.status === "failed" && (
                        <div className="mt-4 space-y-3">
                          <StatusMessage tone="error">
                            {execution.error_message || t("execution.failed")}
                          </StatusMessage>
                          {canCreate && (
                            <Button
                              variant="secondary"
                              onClick={() => void startExecution(project)}
                              disabled={startingProjectId === project.id}
                            >
                              <RefreshCw className="h-4 w-4" />
                              {t("execution.newCycle")}
                            </Button>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
                <ThreeDProjectPanel project={project} canWrite={canCreate} />
              </article>
            );
          })}
        </div>

        {!projects.length && !loading && !error && (
          <div className="mt-10 rounded-3xl border border-dashed border-white/10 p-10 text-center sm:p-16">
            <FolderKanban className="mx-auto h-10 w-10 text-white/20" />
            <h2 className="mt-5 text-xl font-semibold">{t("emptyTitle")}</h2>
            <p className="mx-auto mt-3 max-w-xl text-sm leading-7 text-white/45">
              {t("emptyCopy")}
            </p>
            {canCreate && workspaces.length > 0 && (
              <Button className="mt-6" onClick={() => setShowCreate(true)}>
                {t("newProject")}
                <ArrowUpRight className="h-4 w-4" />
              </Button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
