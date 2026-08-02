"use client";

import { ArrowUpRight, FolderKanban, Gauge, LoaderCircle, Plus, RefreshCw, Tags } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import { createProject, getFreeTierStatus, listProjects, listWorkspaces } from "@/lib/api";
import type { FreeTierStatus, Project, Workspace } from "@/types";

function errorText(cause: unknown, fallback: string): string {
  void cause;
  return fallback;
}

export function ProjectsClient() {
  const t = useTranslations("projects");
  const locale = useLocale();
  const router = useRouter();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [quota, setQuota] = useState<FreeTierStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const canCreate = useMemo(
    () => Boolean(user?.permissions.includes("projects:write") || user?.permissions.includes("*")),
    [user]
  );

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError("");
    try {
      const [nextProjects, nextWorkspaces, nextQuota] = await Promise.all([
        listProjects(),
        listWorkspaces(),
        getFreeTierStatus()
      ]);
      setProjects(nextProjects);
      setWorkspaces(nextWorkspaces);
      setQuota(nextQuota);
    } catch (cause) {
      setError(errorText(cause, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, t]);

  useEffect(() => {
    void load();
  }, [load]);

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
        priority: String(form.get("priority") || "medium") as "low" | "medium" | "high" | "critical",
        workspace_id: String(form.get("workspaceId") || ""),
        tags: String(form.get("tags") || "").split(",").map((item) => item.trim()).filter(Boolean).slice(0, 12)
      });
      setProjects((current) => [project, ...current]);
      setShowCreate(false);
      formElement.reset();
      void getFreeTierStatus().then(setQuota).catch(() => undefined);
    } catch (cause) {
      setCreateError(errorText(cause, t("createError")));
    } finally {
      setCreating(false);
    }
  }

  function statusLabel(status: string) {
    const known = ["planning", "active", "in_progress", "completed", "paused", "cancelled"];
    return known.includes(status) ? t(`status.${status}`) : status;
  }

  function priorityLabel(priority: string) {
    const known = ["low", "medium", "high", "critical"];
    return known.includes(priority) ? t(`priorityValue.${priority}`) : priority;
  }

  if (isLoading || (loading && !projects.length)) {
    return <div className="page-shell section-pad flex items-center justify-center gap-3 text-white/50"><LoaderCircle className="h-5 w-5 animate-spin" />{t("loading")}</div>;
  }

  return (
    <section className="section-pad">
      <div className="page-shell">
        <div className="flex flex-col gap-7 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <span className="eyebrow"><FolderKanban className="h-3.5 w-3.5" />{t("eyebrow")}</span>
            <h1 className="section-title mt-7">{t("title")}</h1>
            <p className="section-copy mt-5">{t("description")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              {t("refresh")}
            </Button>
            {canCreate && (
              <Button onClick={() => setShowCreate((current) => !current)} disabled={!workspaces.length}>
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
              <p className="mt-2 text-2xl font-semibold">{quota.usage.projects} / {quota.limits.projects}</p>
            </div>
            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs text-white/35">{t("quota.messages")}</p>
              <p className="mt-2 text-2xl font-semibold">{quota.remaining.user_messages}</p>
            </div>
            <div className="glass-panel rounded-2xl p-5">
              <p className="text-xs text-white/35">{t("quota.responses")}</p>
              <p className="mt-2 text-2xl font-semibold">{quota.remaining.assistant_responses}</p>
            </div>
          </div>
        )}

        {error && <StatusMessage tone="error" className="mt-8">{error}</StatusMessage>}
        {!workspaces.length && !error && <StatusMessage className="mt-8">{t("noWorkspace")}</StatusMessage>}

        {showCreate && (
          <form onSubmit={submitProject} className="glass-panel mt-8 rounded-3xl p-6 sm:p-8">
            <div className="flex items-center gap-3">
              <Plus className="h-5 w-5 text-electric-200" />
              <h2 className="text-xl font-semibold">{t("createTitle")}</h2>
            </div>
            <div className="mt-7 grid gap-5 sm:grid-cols-2">
              <div>
                <label htmlFor="project-name" className="field-label">{t("name")}</label>
                <input id="project-name" name="name" className="field-control" minLength={2} maxLength={160} required />
              </div>
              <div>
                <label htmlFor="project-workspace" className="field-label">{t("workspace")}</label>
                <select id="project-workspace" name="workspaceId" className="field-control" required defaultValue={workspaces[0]?.id || ""}>
                  {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id} className="bg-ink-800">{workspace.name}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="project-priority" className="field-label">{t("priority")}</label>
                <select id="project-priority" name="priority" className="field-control" defaultValue="medium">
                  {(["low", "medium", "high", "critical"] as const).map((value) => <option key={value} value={value} className="bg-ink-800">{t(`priorityValue.${value}`)}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="project-tags" className="field-label">{t("tags")}</label>
                <input id="project-tags" name="tags" className="field-control" maxLength={300} />
                <p className="mt-2 text-xs text-white/30">{t("tagsRule")}</p>
              </div>
              <div className="sm:col-span-2">
                <label htmlFor="project-description" className="field-label">{t("projectDescription")}</label>
                <textarea id="project-description" name="description" className="field-control min-h-32 resize-y" maxLength={2000} />
              </div>
            </div>
            {createError && <StatusMessage tone="error" className="mt-5">{createError}</StatusMessage>}
            <div className="mt-7 flex flex-wrap gap-3">
              <Button type="submit" disabled={creating}>
                {creating ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                {creating ? t("creating") : t("create")}
              </Button>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>{t("cancel")}</Button>
            </div>
          </form>
        )}

        <div className="mt-10 grid gap-5 lg:grid-cols-2">
          {projects.map((project) => (
            <article key={project.id} className="glass-panel rounded-3xl p-6 sm:p-8">
              <div className="flex items-start justify-between gap-5">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-electric-200">{statusLabel(project.status)}</p>
                  <h2 className="mt-3 text-xl font-semibold">{project.name}</h2>
                </div>
                <span className="rounded-lg border border-white/[0.07] px-2.5 py-1 text-xs text-white/40">{priorityLabel(project.priority)}</span>
              </div>
              {project.description && <p className="mt-4 line-clamp-3 text-sm leading-7 text-white/50">{project.description}</p>}
              <div className="mt-6 h-1.5 overflow-hidden rounded-full bg-white/[0.06]" aria-label={t("progress", { value: project.progress })}>
                <div className="h-full rounded-full bg-gradient-to-r from-electric-400 to-violet-500" style={{ width: `${Math.max(0, Math.min(100, project.progress))}%` }} />
              </div>
              <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs text-white/35">
                <span className="inline-flex items-center gap-1.5"><Gauge className="h-3.5 w-3.5" />{project.progress}%</span>
                <span>{project.workspace}</span>
                <span>{t("tasks", { count: project.task_count })}</span>
              </div>
              {project.tags.length > 0 && (
                <div className="mt-5 flex flex-wrap items-center gap-2">
                  <Tags className="h-3.5 w-3.5 text-white/25" />
                  {project.tags.map((tag) => <span key={tag} className="rounded-md bg-white/[0.05] px-2 py-1 text-[11px] text-white/40">{tag}</span>)}
                </div>
              )}
            </article>
          ))}
        </div>

        {!projects.length && !loading && !error && (
          <div className="mt-10 rounded-3xl border border-dashed border-white/10 p-10 text-center sm:p-16">
            <FolderKanban className="mx-auto h-10 w-10 text-white/20" />
            <h2 className="mt-5 text-xl font-semibold">{t("emptyTitle")}</h2>
            <p className="mx-auto mt-3 max-w-xl text-sm leading-7 text-white/45">{t("emptyCopy")}</p>
            {canCreate && workspaces.length > 0 && <Button className="mt-6" onClick={() => setShowCreate(true)}>{t("newProject")}<ArrowUpRight className="h-4 w-4" /></Button>}
          </div>
        )}
      </div>
    </section>
  );
}
