"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  Box,
  Code2,
  Download,
  FileText,
  Film,
  Image,
  Layout,
  Loader2,
  Megaphone,
  Music2,
  Palette,
  Paperclip,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import {
  archiveStudioAsset,
  attachStudioAsset,
  cancelStudioJob,
  createStudioJob,
  createStudioRevision,
  downloadStudioAsset,
  getStudioDepartments,
  listProjectOptions,
  listStudioAssets,
  listStudioJobs,
  retryStudioJob,
  type ProjectOption,
  type StudioAsset,
  type StudioDepartment,
  type StudioJob,
} from "@/lib/studio-api";

const fallbackDepartments: StudioDepartment[] = [
  {
    id: "text",
    name: "Text Studio",
    asset_type: "text",
    outputs: ["Markdown", "JSON", "ZIP"],
  },
  {
    id: "website",
    name: "Website Studio",
    asset_type: "website",
    outputs: ["HTML", "CSS", "JavaScript", "ZIP"],
  },
  {
    id: "code",
    name: "Code Studio",
    asset_type: "code",
    outputs: ["source", "tests", "README", "ZIP"],
  },
  {
    id: "ui-ux",
    name: "UI/UX Studio",
    asset_type: "ui-ux",
    outputs: ["design system", "wireframe", "prototype brief"],
  },
  {
    id: "three-d",
    name: "3D & Three.js Studio",
    asset_type: "three-d",
    outputs: ["Three.js scene", "GLTF-ready structure", "ZIP"],
  },
  {
    id: "audio",
    name: "Audio Studio",
    asset_type: "audio",
    outputs: ["narration", "SSML", "cue sheet", "mix notes"],
  },
  {
    id: "video",
    name: "Video Studio",
    asset_type: "video",
    outputs: ["script", "shot list", "subtitles", "render plan"],
  },
  {
    id: "animation",
    name: "Animation Studio",
    asset_type: "animation",
    outputs: ["storyboard", "timing sheet", "scene plan"],
  },
  {
    id: "advertising",
    name: "Advertising Studio",
    asset_type: "advertising",
    outputs: ["campaign brief", "ad variants", "CTA plan"],
  },
  {
    id: "documentary",
    name: "Documentary Studio",
    asset_type: "documentary",
    outputs: ["research outline", "narration", "evidence checklist"],
  },
  {
    id: "image",
    name: "Image Studio",
    asset_type: "image",
    outputs: ["editable SVG", "prompt pack", "export guide"],
  },
  {
    id: "branding",
    name: "Branding Studio",
    asset_type: "branding",
    outputs: ["brand strategy", "identity tokens", "usage guide"],
  },
];

const icons = {
  text: FileText,
  website: Layout,
  code: Code2,
  "ui-ux": Palette,
  "three-d": Box,
  audio: Music2,
  video: Film,
  animation: Sparkles,
  advertising: Megaphone,
  documentary: Film,
  image: Image,
  branding: Palette,
} as const;

const terminalStatuses = new Set([
  "completed",
  "blocked",
  "failed",
  "cancelled",
]);

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function StudioPage() {
  const [departments, setDepartments] =
    useState<StudioDepartment[]>(fallbackDepartments);
  const [department, setDepartment] = useState("text");
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState("");
  const [style, setStyle] = useState("modern cinematic");
  const [target, setTarget] = useState("");
  const [language, setLanguage] = useState("en-US");
  const [programmingLanguage, setProgrammingLanguage] = useState("python");
  const [projectId, setProjectId] = useState("");
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [jobs, setJobs] = useState<StudioJob[]>([]);
  const [assets, setAssets] = useState<StudioAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState(
    "Loading durable Production Studio...",
  );

  const selected = useMemo(
    () => departments.find((item) => item.id === department),
    [department, departments],
  );
  const hasActiveJobs = jobs.some((job) => !terminalStatuses.has(job.status));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [departmentResult, jobRows, assetRows, projectRows] =
        await Promise.all([
          getStudioDepartments(),
          listStudioJobs(),
          listStudioAssets(),
          listProjectOptions(),
        ]);
      setDepartments(departmentResult.departments);
      setJobs(jobRows);
      setAssets(assetRows);
      setProjects(projectRows);
      setDepartment((current) =>
        departmentResult.departments.length &&
        !departmentResult.departments.some((item) => item.id === current)
          ? departmentResult.departments[0].id
          : current,
      );
      setMessage(
        "Studio jobs, assets, revisions, safety evidence, and projects synchronized.",
      );
    } catch {
      setMessage("The durable Production Studio backend is unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLanguage(document.documentElement.lang || "en-US");
    void load();
  }, [load]);

  useEffect(() => {
    if (!hasActiveJobs) return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveJobs, load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy("create");
    setMessage("Queueing provider-neutral Studio job...");
    try {
      const job = await createStudioJob({
        department,
        title,
        brief,
        language,
        style,
        target: target || null,
        programming_language:
          department === "code" ? programmingLanguage : null,
        project_id: projectId || null,
      });
      setJobs((current) => [job, ...current]);
      setTitle("");
      setBrief("");
      setMessage(
        "Studio job queued. The worker will persist safety evidence and the downloadable asset.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Studio job failed to queue.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function download(asset: StudioAsset) {
    setBusy(asset.id);
    setMessage("Verifying Studio asset integrity...");
    try {
      const blob = await downloadStudioAsset(asset.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = asset.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setMessage("Asset checksum verified and download started.");
    } catch {
      setMessage("Asset download failed integrity or access validation.");
    } finally {
      setBusy(null);
    }
  }

  async function revise(asset: StudioAsset) {
    const revisionBrief = window.prompt(
      "Describe the exact changes required for the next durable revision:",
    );
    if (!revisionBrief?.trim()) return;
    const changeNote = window.prompt(
      "Revision note:",
      "Requested Studio revision",
    );
    if (!changeNote?.trim()) return;
    setBusy(asset.id);
    try {
      const job = await createStudioRevision(asset.id, {
        brief: revisionBrief,
        change_note: changeNote,
      });
      setJobs((current) => [job, ...current]);
      setMessage(
        "Revision job queued without overwriting the previous artifact.",
      );
    } catch {
      setMessage("Studio revision could not be queued.");
    } finally {
      setBusy(null);
    }
  }

  async function attach(asset: StudioAsset) {
    const targetProject = projectId || projects[0]?.id;
    if (!targetProject) {
      setMessage("Create or select a project before attaching an asset.");
      return;
    }
    setBusy(asset.id);
    try {
      await attachStudioAsset(asset.id, targetProject);
      setMessage("Studio asset attached to the governed project history.");
      await load();
    } catch {
      setMessage("Studio asset attachment failed.");
    } finally {
      setBusy(null);
    }
  }

  async function archive(asset: StudioAsset) {
    if (
      !window.confirm(
        "Archive this Studio asset while retaining all revisions and audit evidence?",
      )
    )
      return;
    setBusy(asset.id);
    try {
      await archiveStudioAsset(asset.id);
      setAssets((current) => current.filter((item) => item.id !== asset.id));
      setMessage(
        "Studio asset archived; revisions and evidence were retained.",
      );
    } catch {
      setMessage("Studio asset could not be archived.");
    } finally {
      setBusy(null);
    }
  }

  async function retry(job: StudioJob) {
    setBusy(job.id);
    try {
      const updated = await retryStudioJob(job.id);
      setJobs((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage("Studio job safely returned to the durable queue.");
    } catch {
      setMessage("Studio job could not be retried.");
    } finally {
      setBusy(null);
    }
  }

  async function cancel(job: StudioJob) {
    setBusy(job.id);
    try {
      const updated = await cancelStudioJob(job.id);
      setJobs((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage("Studio job cancellation was persisted.");
    } catch {
      setMessage("Studio job could not be cancelled.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-electric-300">
            AIONEX Production
          </p>
          <h1 className="mt-2 text-3xl font-bold text-white">
            Durable Creative &amp; Developer Studio
          </h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-white/50">
            Provider-neutral text, image, audio, video, web, code, design, and
            3D jobs with durable assets, revisions, safety evidence, verified
            downloads, and project attachment. External media providers remain
            reserved for Phase 29J.
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="btn-primary disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh Studio
        </button>
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
        {departments.map((item) => {
          const Icon = icons[item.id as keyof typeof icons] ?? Sparkles;
          const active = item.id === department;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setDepartment(item.id)}
              className={`glass-card p-4 text-left transition ${active ? "border-electric-400/50 bg-electric-500/10" : "hover:bg-white/[0.04]"}`}
            >
              <Icon
                className={`h-5 w-5 ${active ? "text-electric-300" : "text-white/40"}`}
              />
              <div className="mt-3 text-sm font-semibold text-white">
                {item.name}
              </div>
              <div className="mt-1 text-xs leading-5 text-white/40">
                {item.outputs.join(" · ")}
              </div>
            </button>
          );
        })}
      </div>

      <form
        onSubmit={submit}
        className="glass-card grid gap-5 p-6 lg:grid-cols-[1fr_340px]"
      >
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-white">
              {selected?.name ?? "Production Studio"}
            </h2>
            <p className="mt-1 text-sm text-white/40">
              Every request becomes a durable job before a protected asset is
              published.
            </p>
          </div>
          <input
            required
            minLength={2}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Project title"
            className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
          />
          <textarea
            required
            minLength={8}
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder="Describe the output, audience, scenes, dimensions, accessibility, evidence, and source requirements..."
            className="glass-input min-h-48 w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              value={style}
              onChange={(event) => setStyle(event.target.value)}
              placeholder="Style"
              className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"
            />
            <input
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              placeholder="Target audience or platform"
              className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"
            />
          </div>
          <select
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
          >
            <option value="" className="bg-space-900">
              No project attachment yet
            </option>
            {projects.map((project) => (
              <option
                key={project.id}
                value={project.id}
                className="bg-space-900"
              >
                {project.name}
              </option>
            ))}
          </select>
          {department === "code" && (
            <select
              value={programmingLanguage}
              onChange={(event) => setProgrammingLanguage(event.target.value)}
              className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
            >
              {[
                "python",
                "typescript",
                "javascript",
                "go",
                "rust",
                "java",
                "csharp",
                "php",
                "swift",
                "kotlin",
                "dart",
              ].map((item) => (
                <option key={item} value={item} className="bg-space-900">
                  {item}
                </option>
              ))}
            </select>
          )}
          <button disabled={busy !== null} className="btn-primary">
            {busy === "create" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Queue durable Studio job
          </button>
        </div>
        <aside className="rounded-2xl border border-white/[0.06] bg-black/20 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-white/35">
            Governed output contract
          </div>
          <div className="mt-4 space-y-3 text-sm text-white/60">
            <p>✓ Persistent job status and retry history</p>
            <p>✓ Provider-neutral editable source package</p>
            <p>✓ Safety review and immutable evidence</p>
            <p>✓ SHA-256 verified protected download</p>
            <p>✓ Non-destructive revisions</p>
            <p>✓ Project history attachment</p>
            <p>✓ Zero external provider requests or cost</p>
          </div>
          <p className="mt-5 text-xs leading-5 text-amber-200/70">
            No rendered external media is presented as real until a governed
            provider is activated in Phase 29J.
          </p>
        </aside>
      </form>

      <section className="glass-card p-5">
        <h2 className="text-lg font-semibold text-white">Studio job queue</h2>
        <div className="mt-4 space-y-3">
          {!jobs.length && (
            <div className="text-sm text-white/40">
              No Studio jobs recorded.
            </div>
          )}
          {jobs.slice(0, 20).map((job) => (
            <div
              key={job.id}
              className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-white">
                    {job.title}
                  </div>
                  <div className="mt-1 text-xs text-white/35">
                    {job.department} · {job.status} · {job.progress}% · attempt{" "}
                    {job.attempts}/{job.max_attempts}
                  </div>
                  {job.error_message && (
                    <div className="mt-1 text-xs text-red-300">
                      {job.error_message}
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  {["failed", "cancelled"].includes(job.status) && (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void retry(job)}
                      className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300"
                    >
                      <RotateCcw className="mr-1 inline h-3.5 w-3.5" /> Retry
                    </button>
                  )}
                  {["queued", "running"].includes(job.status) && (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void cancel(job)}
                      className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="glass-card p-5">
        <h2 className="text-lg font-semibold text-white">
          Protected asset library
        </h2>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {!assets.length && (
            <div className="text-sm text-white/40">
              No completed Studio assets yet.
            </div>
          )}
          {assets.map((asset) => (
            <div
              key={asset.id}
              className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
            >
              <div className="flex items-start gap-3">
                <ShieldCheck className="mt-0.5 h-5 w-5 text-green-300" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-white">
                    {asset.title}
                  </div>
                  <div className="mt-1 text-xs text-white/35">
                    {asset.asset_type} · revision {asset.current_revision} ·{" "}
                    {formatBytes(asset.size_bytes)}
                  </div>
                  <div className="mt-1 truncate font-mono text-[10px] text-white/25">
                    SHA-256 {asset.checksum}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void download(asset)}
                      className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300"
                    >
                      <Download className="mr-1 inline h-3.5 w-3.5" /> Download
                    </button>
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void revise(asset)}
                      className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white/65"
                      aria-label="New revision"
                    >
                      <RotateCcw className="mr-1 inline h-3.5 w-3.5" /> New
                      revision
                    </button>
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void attach(asset)}
                      className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white/65"
                      aria-label="Attach to project"
                    >
                      <Paperclip className="mr-1 inline h-3.5 w-3.5" /> Attach
                      to project
                    </button>
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void archive(asset)}
                      className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white/45"
                    >
                      <Archive className="mr-1 inline h-3.5 w-3.5" /> Archive
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
