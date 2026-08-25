"use client";

import {
  Archive,
  Box,
  Code2,
  Download,
  FileText,
  Film,
  FolderKanban,
  Image as ImageIcon,
  Layout,
  LoaderCircle,
  Music2,
  Palette,
  Paperclip,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  WandSparkles,
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
import { useAuth } from "@/hooks/use-auth";
import { createProject, listProjects, listWorkspaces } from "@/lib/api";
import {
  attachStudioAsset,
  cancelStudioJob,
  createStudioJob,
  createStudioRevision,
  downloadStudioAsset,
  getStudioDepartments,
  getStudioHub,
  getStudioSectorPacks,
  listStudioAssets,
  listStudioJobs,
  listStudioRevisions,
  retryStudioJob,
  type StudioAsset,
  type StudioDepartment,
  type StudioHubSnapshot,
  type StudioJob,
  type StudioRevision,
  type StudioSectorCatalog,
  type StudioSectorPack,
} from "@/lib/studio-api";
import type { Project, Workspace } from "@/types";

const terminalStatuses = new Set(["completed", "blocked", "failed", "cancelled"]);

const departmentIcons = {
  text: FileText,
  website: Layout,
  code: Code2,
  "ui-ux": Palette,
  "three-d": Box,
  audio: Music2,
  video: Film,
  animation: Sparkles,
  advertising: WandSparkles,
  documentary: Film,
  image: ImageIcon,
  branding: Palette,
} as const;

const familyPresets = [
  { key: "software", capability: "software", department: "code", style: "production software" },
  { key: "prompts", capability: "prompt-text", department: "text", style: "structured prompt system" },
  { key: "design", capability: "design-image", department: "ui-ux", style: "accessible product design" },
  { key: "image", capability: "design-image", department: "image", style: "production visual design" },
  { key: "audio", capability: "audio", department: "audio", style: "clean production audio" },
  { key: "video", capability: "video-motion", department: "video", style: "cinematic production video" },
  { key: "music", capability: "music-song", department: null, style: "music production package" },
  { key: "threeD", capability: "three-d-xr", department: "three-d", style: "interactive 3D/XR" },
  { key: "courses", capability: "courses", department: null, style: "structured learning package" },
  { key: "sector", capability: "sector-solutions", department: null, style: "sector solution blueprint" },
] as const;

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function numericMetadata(job: StudioJob, key: string): number {
  const result = job.result_metadata?.[key];
  if (typeof result === "number") return result;
  const request = job.request_metadata?.[key];
  return typeof request === "number" ? request : 0;
}

export function StudioClient() {
  const t = useTranslations("studio");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [departments, setDepartments] = useState<StudioDepartment[]>([]);
  const [hub, setHub] = useState<StudioHubSnapshot | null>(null);
  const [department, setDepartment] = useState("text");
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [sectorCatalog, setSectorCatalog] = useState<StudioSectorCatalog | null>(null);
  const [sectorWorkspaceId, setSectorWorkspaceId] = useState("");
  const [jobs, setJobs] = useState<StudioJob[]>([]);
  const [assets, setAssets] = useState<StudioAsset[]>([]);
  const [revisions, setRevisions] = useState<Record<string, StudioRevision[]>>({});
  const [attachmentTargets, setAttachmentTargets] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [style, setStyle] = useState("modern production");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const selectedDepartment = useMemo(
    () => departments.find((item) => item.id === department),
    [department, departments],
  );
  const activeJobs = useMemo(
    () => jobs.filter((job) => !terminalStatuses.has(job.status)),
    [jobs],
  );
  const capabilityMap = useMemo(
    () => Object.fromEntries((hub?.capabilities || []).map((item) => [item.capability_id, item])),
    [hub],
  );
  const departmentAvailability = useMemo(() => {
    const result: Record<string, boolean> = {};
    for (const capability of hub?.capabilities || []) {
      for (const item of capability.departments) result[item] = capability.available;
    }
    return result;
  }, [hub]);

  const load = useCallback(async (quiet = false) => {
    if (!isAuthenticated) return;
    if (!quiet) setLoading(true);
    if (!quiet) setError("");
    try {
      const [hubResult, departmentResult, sectorResult, projectRows, workspaceRows, jobRows, assetRows] =
        await Promise.all([
          getStudioHub(),
          getStudioDepartments(),
          getStudioSectorPacks(),
          listProjects(),
          listWorkspaces(),
          listStudioJobs(),
          listStudioAssets(),
        ]);
      setHub(hubResult);
      setDepartments(departmentResult.departments);
      setSectorCatalog(sectorResult);
      setProjects(projectRows);
      setWorkspaces(workspaceRows);
      setSectorWorkspaceId((current) => current || workspaceRows[0]?.id || "");
      setJobs(jobRows);
      setAssets(assetRows);
      setDepartment((current) =>
        departmentResult.departments.some((item) => item.id === current)
          ? current
          : departmentResult.departments[0]?.id || "text",
      );
    } catch (cause) {
      if (!quiet) setError(errorText(cause, t("loadError")));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [isAuthenticated, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!activeJobs.length) return;
    const timer = window.setInterval(() => void load(true), 3000);
    return () => window.clearInterval(timer);
  }, [activeJobs.length, load]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("create");
    setError("");
    setMessage("");
    try {
      if (departmentAvailability[department] === false) {
        setError(t("ownerDisabled"));
        return;
      }
      const job = await createStudioJob({
        department,
        title: String(values.get("title") || "").trim(),
        brief: String(values.get("brief") || "").trim(),
        language: locale,
        style: String(values.get("style") || style).trim(),
        target: String(values.get("target") || "").trim() || null,
        programming_language:
          department === "code"
            ? String(values.get("programming_language") || "python")
            : null,
        project_id: String(values.get("project_id") || "").trim() || null,
      });
      setJobs((current) => [job, ...current]);
      form.reset();
      setStyle("modern production");
      setMessage(t("queued"));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  async function jobAction(job: StudioJob, action: "retry" | "cancel") {
    if (action === "cancel" && !window.confirm(t("cancelConfirm"))) return;
    setBusy(job.id);
    setError("");
    try {
      const updated =
        action === "retry"
          ? await retryStudioJob(job.id)
          : await cancelStudioJob(job.id);
      setJobs((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage(action === "retry" ? t("retryQueued") : t("cancelled"));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  async function download(asset: StudioAsset) {
    setBusy(asset.id);
    setError("");
    try {
      const { blob, filename } = await downloadStudioAsset(asset.id);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename || asset.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
      setMessage(t("downloadStarted"));
    } catch (cause) {
      setError(errorText(cause, t("downloadError")));
    } finally {
      setBusy(null);
    }
  }

  async function revise(asset: StudioAsset) {
    const brief = window.prompt(t("revisionPrompt"));
    if (!brief?.trim()) return;
    const note = window.prompt(t("revisionNotePrompt"));
    if (!note?.trim()) return;
    setBusy(asset.id);
    setError("");
    try {
      const job = await createStudioRevision(asset.id, {
        brief: brief.trim(),
        change_note: note.trim(),
      });
      setJobs((current) => [job, ...current]);
      setMessage(t("revisionQueued"));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  async function toggleHistory(asset: StudioAsset) {
    if (revisions[asset.id]) {
      setRevisions((current) => {
        const next = { ...current };
        delete next[asset.id];
        return next;
      });
      return;
    }
    setBusy(asset.id);
    setError("");
    try {
      const rows = await listStudioRevisions(asset.id);
      setRevisions((current) => ({ ...current, [asset.id]: rows }));
    } catch (cause) {
      setError(errorText(cause, t("historyError")));
    } finally {
      setBusy(null);
    }
  }

  async function attach(asset: StudioAsset) {
    const projectId = attachmentTargets[asset.id] || projects[0]?.id || "";
    if (!projectId) return;
    setBusy(asset.id);
    setError("");
    try {
      await attachStudioAsset(asset.id, projectId);
      setAssets((current) =>
        current.map((item) =>
          item.id === asset.id && !item.attached_project_ids.includes(projectId)
            ? {
                ...item,
                attached_project_ids: [...item.attached_project_ids, projectId],
              }
            : item,
        ),
      );
      setMessage(t("attached"));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  function capabilityUnavailableMessage(reason: string | undefined): string {
    if (reason === "external_activation_required") return t("availability.externalActivation");
    if (reason === "plan_not_supported" || reason === "plan_not_eligible") return t("availability.plan");
    return t("availability.owner");
  }

  async function createSectorProject(pack: StudioSectorPack) {
    if (!sectorCatalog?.capability.available) {
      setError(capabilityUnavailableMessage(sectorCatalog?.capability.availability_reason));
      return;
    }
    if (!sectorWorkspaceId) {
      setError(t("sectorWorkspaceRequired"));
      return;
    }
    setBusy(`sector:${pack.key}`);
    setError("");
    setMessage("");
    try {
      const blueprint = JSON.stringify(pack.domain_blueprint);
      const project = await createProject({
        name: pack.title,
        description: [
          `Phase 36M governed sector pack: ${pack.title}.`,
          `Objective: ${pack.objective}`,
          `Audience: ${pack.audience}`,
          `Roles: ${pack.roles.join(", ")}`,
          `Workflows: ${pack.workflows.join(" | ")}`,
          pack.safety_boundaries.length ? `Safety boundaries: ${pack.safety_boundaries.join(" | ")}` : "",
          pack.external_gates.length ? `External activation gates: ${pack.external_gates.join(" | ")}` : "",
          `Domain Blueprint v3: ${blueprint}`,
        ].filter(Boolean).join("\n"),
        priority: "medium",
        workspace_id: sectorWorkspaceId,
        tags: ["phase36m", "domain-blueprint-v3", `sector:${pack.key}`],
      });
      setProjects((current) => [project, ...current]);
      setMessage(t("sectorProjectCreated", { name: project.name }));
    } catch (cause) {
      setError(errorText(cause, t("sectorProjectError")));
    } finally {
      setBusy(null);
    }
  }

  async function createCustomSectorProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sectorCatalog?.capability.available) {
      setError(capabilityUnavailableMessage(sectorCatalog?.capability.availability_reason));
      return;
    }
    if (!sectorWorkspaceId) {
      setError(t("sectorWorkspaceRequired"));
      return;
    }
    const form = event.currentTarget;
    const values = new FormData(form);
    const title = String(values.get("sector_title") || "").trim();
    const objective = String(values.get("sector_objective") || "").trim();
    const audience = String(values.get("sector_audience") || "").trim();
    setBusy("sector:custom");
    setError("");
    setMessage("");
    try {
      const project = await createProject({
        name: title,
        description: [
          "Phase 36M custom lawful sector request using the governed Domain Blueprint v3 composer.",
          `Objective: ${objective}`,
          `Audience: ${audience}`,
          "Required: infer bounded roles, entities and workflows; retain human/external authority gates; do not create a sector-specific code fork.",
        ].join("\n"),
        priority: "medium",
        workspace_id: sectorWorkspaceId,
        tags: ["phase36m", "domain-blueprint-v3", "sector:custom"],
      });
      setProjects((current) => [project, ...current]);
      form.reset();
      setMessage(t("sectorProjectCreated", { name: project.name }));
    } catch (cause) {
      setError(errorText(cause, t("sectorProjectError")));
    } finally {
      setBusy(null);
    }
  }

  if (isLoading || (!isAuthenticated && !isLoading)) {
    return (
      <section className="page-shell py-16 text-white">
        <div className="glass-panel flex min-h-52 items-center justify-center rounded-3xl">
          <LoaderCircle className="h-7 w-7 animate-spin text-electric-200" />
        </div>
      </section>
    );
  }

  return (
    <section className="page-shell py-10 text-white sm:py-14">
      <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
        <div className="max-w-3xl">
          <span className="eyebrow">
            <Sparkles className="h-3.5 w-3.5" /> {t("eyebrow")}
          </span>
          <h1 className="section-title mt-6">{t("title")}</h1>
          <p className="section-copy mt-4">{t("description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => router.push(`/${locale}/projects`)}>
            <FolderKanban className="h-4 w-4" /> {t("projectsLink")}
          </Button>
          <Button variant="secondary" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("refresh")}
          </Button>
        </div>
      </div>

      <div className="glass-panel mt-8 rounded-3xl p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-electric-200" />
          <div>
            <p className="text-sm font-semibold">{t("governedTitle")}</p>
            <p className="mt-1 text-xs leading-6 text-white/45">{t("governedCopy")}</p>
          </div>
        </div>
      </div>

      <div className="mt-8">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{t("templatesTitle")}</h2>
            <p className="mt-1 text-xs text-white/40">{t("templatesCopy")}</p>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {familyPresets.map((preset) => {
            const capability = capabilityMap[preset.capability];
            const available = capability?.available ?? true;
            const active = preset.department !== null && department === preset.department && style === preset.style;
            return (
              <button
                type="button"
                key={preset.key}
                disabled={!available}
                onClick={() => {
                  if (!available) return;
                  if (capability?.launch_surface === "academy") {
                    router.push(`/${locale}/academy`);
                    return;
                  }
                  if (capability?.launch_surface === "studio-sectors") {
                    document.getElementById("studio-sector-solutions")?.scrollIntoView({ behavior: "smooth" });
                    return;
                  }
                  if (preset.department === null) {
                    router.push(`/${locale}/projects`);
                    return;
                  }
                  setDepartment(preset.department);
                  setStyle(preset.style);
                }}
                className={`rounded-2xl border p-4 text-start transition disabled:cursor-not-allowed disabled:opacity-40 ${
                  active
                    ? "border-electric-300/40 bg-electric-300/10"
                    : "border-white/[0.07] bg-white/[0.025] hover:bg-white/[0.05]"
                }`}
                title={!available ? capabilityUnavailableMessage(capability?.availability_reason) : capability?.external_gates.join(" · ") || undefined}
              >
                <Sparkles className="h-4 w-4 text-electric-200" />
                <div className="mt-3 text-sm font-semibold">{t(`families.${preset.key}`)}</div>
              </button>
            );
          })}
        </div>
      </div>

      {sectorCatalog && (
        <section id="studio-sector-solutions" className="mt-10 scroll-mt-28">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold">{t("sectorTitle")}</h2>
              <p className="mt-1 max-w-3xl text-xs leading-6 text-white/40">{t("sectorCopy")}</p>
            </div>
            <select
              className="field-control min-w-52"
              value={sectorWorkspaceId}
              onChange={(event) => setSectorWorkspaceId(event.target.value)}
              disabled={!workspaces.length}
              aria-label={t("sectorWorkspace")}
            >
              {!workspaces.length && <option value="">{t("sectorNoWorkspace")}</option>}
              {workspaces.map((workspace) => (
                <option className="bg-ink-800" key={workspace.id} value={workspace.id}>{workspace.name}</option>
              ))}
            </select>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {sectorCatalog.packs.map((pack) => (
              <article key={pack.key} className="glass-panel rounded-2xl p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold">{pack.title}</p>
                    <p className="mt-2 text-xs leading-5 text-white/40">{pack.objective}</p>
                  </div>
                  <span className="rounded-full border border-white/[0.08] px-2 py-1 text-[10px] text-white/40">v3</span>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 text-[10px] text-white/45">
                  <span className="rounded-full bg-white/[0.04] px-2 py-1">{pack.entity_count} {t("sectorEntities")}</span>
                  <span className="rounded-full bg-white/[0.04] px-2 py-1">{pack.workflow_count} {t("sectorWorkflows")}</span>
                  {pack.external_gates.length > 0 && <span className="rounded-full bg-amber-500/10 px-2 py-1 text-amber-200/70">{pack.external_gates.length} {t("sectorGates")}</span>}
                </div>
                <p className="mt-4 text-[11px] leading-5 text-white/35">{pack.workflows.slice(0, 3).join(" · ")}</p>
                <Button
                  className="mt-5"
                  size="sm"
                  disabled={!sectorCatalog.capability.available || !workspaces.length || busy === `sector:${pack.key}`}
                  onClick={() => void createSectorProject(pack)}
                >
                  {busy === `sector:${pack.key}` ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <FolderKanban className="h-3.5 w-3.5" />}
                  {t("sectorUseProject")}
                </Button>
              </article>
            ))}
          </div>

          <form onSubmit={createCustomSectorProject} className="glass-panel mt-5 rounded-2xl p-5 sm:p-6">
            <div className="flex items-center gap-3">
              <WandSparkles className="h-4 w-4 text-electric-200" />
              <div>
                <p className="text-sm font-semibold">{t("customSectorTitle")}</p>
                <p className="mt-1 text-xs text-white/35">{t("customSectorCopy")}</p>
              </div>
            </div>
            <div className="mt-5 grid gap-4 sm:grid-cols-3">
              <input name="sector_title" className="field-control" placeholder={t("customSectorName")} minLength={2} maxLength={160} required />
              <input name="sector_audience" className="field-control" placeholder={t("customSectorAudience")} minLength={2} maxLength={240} required />
              <input name="sector_objective" className="field-control" placeholder={t("customSectorObjective")} minLength={10} maxLength={1000} required />
            </div>
            <Button className="mt-4" size="sm" disabled={!sectorCatalog.capability.available || !workspaces.length || busy === "sector:custom"}>
              {busy === "sector:custom" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              {t("customSectorCreate")}
            </Button>
          </form>
        </section>
      )}

      {error && (
        <StatusMessage tone="error" className="mt-8">
          {error}
        </StatusMessage>
      )}
      {message && <StatusMessage className="mt-8">{message}</StatusMessage>}

      <div className="mt-8 grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <form onSubmit={submit} className="glass-panel rounded-3xl p-5 sm:p-7">
          <div className="flex items-center gap-3">
            <WandSparkles className="h-5 w-5 text-electric-200" />
            <h2 className="text-lg font-semibold">{t("createTitle")}</h2>
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <div>
              <label className="field-label" htmlFor="studio-department">{t("department")}</label>
              <select
                id="studio-department"
                className="field-control"
                value={department}
                onChange={(event) => setDepartment(event.target.value)}
                required
              >
                {departments.map((item) => (
                  <option
                    className="bg-ink-800"
                    key={item.id}
                    value={item.id}
                    disabled={departmentAvailability[item.id] === false}
                  >
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="field-label" htmlFor="studio-project">{t("project")}</label>
              <select id="studio-project" name="project_id" className="field-control" defaultValue="">
                <option className="bg-ink-800" value="">{t("projectOptional")}</option>
                {projects.map((project) => (
                  <option className="bg-ink-800" key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="field-label" htmlFor="studio-title">{t("titleLabel")}</label>
              <input id="studio-title" name="title" className="field-control" minLength={2} maxLength={160} required />
            </div>
            <div className="sm:col-span-2">
              <label className="field-label" htmlFor="studio-brief">{t("brief")}</label>
              <textarea id="studio-brief" name="brief" className="field-control min-h-36 resize-y" minLength={8} maxLength={12000} required />
            </div>
            <div>
              <label className="field-label" htmlFor="studio-style">{t("style")}</label>
              <input id="studio-style" name="style" className="field-control" value={style} onChange={(event) => setStyle(event.target.value)} minLength={2} maxLength={120} required />
            </div>
            <div>
              <label className="field-label" htmlFor="studio-target">{t("target")}</label>
              <input id="studio-target" name="target" className="field-control" maxLength={240} />
            </div>
            {department === "code" && (
              <div className="sm:col-span-2">
                <label className="field-label" htmlFor="studio-language">{t("programmingLanguage")}</label>
                <select id="studio-language" name="programming_language" className="field-control" defaultValue="python">
                  {['python', 'typescript', 'javascript', 'rust', 'go', 'java', 'php'].map((value) => (
                    <option className="bg-ink-800" value={value} key={value}>{value}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {selectedDepartment && (
            <div className="mt-5 rounded-2xl border border-white/[0.06] bg-black/10 p-4 text-xs text-white/40">
              <p className="font-semibold text-white/60">{selectedDepartment.name}</p>
              <p className="mt-2">{selectedDepartment.outputs.join(" · ")}</p>
            </div>
          )}

          <Button
            type="submit"
            className="mt-6"
            disabled={
              busy === "create" ||
              !departments.length ||
              departmentAvailability[department] === false
            }
          >
            {busy === "create" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {busy === "create" ? t("queueing") : t("queue")}
          </Button>
        </form>

        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">{t("queueTitle")}</h2>
              <p className="mt-1 text-xs text-white/35">{t("queueCopy")}</p>
            </div>
            <span className="rounded-full border border-white/[0.08] px-3 py-1 text-xs text-white/45">{jobs.length}</span>
          </div>

          {!jobs.length && !loading && (
            <div className="rounded-3xl border border-dashed border-white/10 p-8 text-center text-sm text-white/40">{t("emptyQueue")}</div>
          )}

          {jobs.slice(0, 12).map((job) => {
            const Icon = departmentIcons[job.department as keyof typeof departmentIcons] || Archive;
            const cost = numericMetadata(job, "external_cost_usd");
            return (
              <article key={job.id} className="glass-panel rounded-2xl p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="rounded-xl bg-electric-300/10 p-2 text-electric-200"><Icon className="h-4 w-4" /></div>
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-semibold">{job.title}</h3>
                      <p className="mt-1 text-[11px] text-white/35">{job.department} · {job.output_kind}</p>
                    </div>
                  </div>
                  <span className="rounded-full border border-white/[0.08] px-2.5 py-1 text-[11px] text-white/50">{job.status}</span>
                </div>

                <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                  <div className="h-full rounded-full bg-gradient-to-r from-electric-400 to-violet-500" style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <div className="rounded-xl bg-black/10 p-3"><div className="text-[10px] text-white/30">{t("progress")}</div><div className="mt-1 text-xs">{job.progress}%</div></div>
                  <div className="rounded-xl bg-black/10 p-3"><div className="text-[10px] text-white/30">{t("provider")}</div><div className="mt-1 truncate text-xs">{job.provider || t("providerNeutral")}</div></div>
                  <div className="rounded-xl bg-black/10 p-3"><div className="text-[10px] text-white/30">{t("cost")}</div><div className="mt-1 text-xs">${cost.toFixed(6)}</div></div>
                  <div className="rounded-xl bg-black/10 p-3"><div className="text-[10px] text-white/30">{t("safety")}</div><div className="mt-1 truncate text-xs">{job.safety_status}</div></div>
                </div>
                {job.error_message && <p className="mt-3 text-xs text-red-300/80">{job.error_message}</p>}
                <div className="mt-4 flex flex-wrap gap-2">
                  {["failed", "cancelled"].includes(job.status) && (
                    <Button variant="secondary" size="sm" disabled={busy === job.id} onClick={() => void jobAction(job, "retry")}>
                      <RotateCcw className="h-3.5 w-3.5" /> {t("retry")}
                    </Button>
                  )}
                  {["queued", "running"].includes(job.status) && (
                    <Button variant="secondary" size="sm" disabled={busy === job.id} onClick={() => void jobAction(job, "cancel")}>
                      {t("cancelJob")}
                    </Button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </div>

      <div className="mt-10">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{t("assetLibrary")}</h2>
            <p className="mt-1 text-xs text-white/35">{t("assetLibraryCopy")}</p>
          </div>
          <span className="rounded-full border border-white/[0.08] px-3 py-1 text-xs text-white/45">{assets.length}</span>
        </div>

        {!assets.length && !loading && (
          <div className="mt-4 rounded-3xl border border-dashed border-white/10 p-8 text-center text-sm text-white/40">{t("emptyAssets")}</div>
        )}

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {assets.map((asset) => (
            <article className="glass-panel rounded-2xl p-5" key={asset.id}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold">{asset.title}</h3>
                  <p className="mt-1 truncate text-[11px] text-white/35">{asset.filename}</p>
                </div>
                <span className="rounded-full border border-white/[0.08] px-2.5 py-1 text-[11px] text-white/45">r{asset.current_revision}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-white/35">
                <span>{asset.asset_type}</span><span>{formatBytes(asset.size_bytes)}</span><span>{asset.status}</span>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button size="sm" disabled={busy === asset.id} onClick={() => void download(asset)}><Download className="h-3.5 w-3.5" /> {t("download")}</Button>
                <Button size="sm" variant="secondary" disabled={busy === asset.id} onClick={() => void revise(asset)}><RotateCcw className="h-3.5 w-3.5" /> {t("revision")}</Button>
                <Button size="sm" variant="secondary" disabled={busy === asset.id} onClick={() => void toggleHistory(asset)}>{t("history")}</Button>
              </div>

              {projects.length > 0 && (
                <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                  <select
                    className="field-control min-w-0 flex-1"
                    value={attachmentTargets[asset.id] || projects[0]?.id || ""}
                    onChange={(event) => setAttachmentTargets((current) => ({ ...current, [asset.id]: event.target.value }))}
                  >
                    {projects.map((project) => <option className="bg-ink-800" key={project.id} value={project.id}>{project.name}</option>)}
                  </select>
                  <Button size="sm" variant="secondary" disabled={busy === asset.id} onClick={() => void attach(asset)}><Paperclip className="h-3.5 w-3.5" /> {t("attach")}</Button>
                </div>
              )}

              {asset.attached_project_ids.length > 0 && (
                <p className="mt-3 text-[11px] text-emerald-300/70">{t("attachedCount", { count: asset.attached_project_ids.length })}</p>
              )}

              {revisions[asset.id] && (
                <div className="mt-4 space-y-2 border-t border-white/[0.06] pt-4">
                  {revisions[asset.id].map((revision) => (
                    <div className="flex items-center justify-between gap-3 rounded-xl bg-black/10 p-3 text-xs" key={revision.id}>
                      <div><span className="font-semibold">r{revision.revision_number}</span><span className="ms-2 text-white/35">{revision.change_note || revision.filename}</span></div>
                      <span className="text-white/35">{formatBytes(revision.size_bytes)}</span>
                    </div>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
