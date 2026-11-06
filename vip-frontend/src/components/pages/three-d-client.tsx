"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  Box,
  Download,
  FileDown,
  FolderKanban,
  Upload,
  LoaderCircle,
  Lock,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
} from "lucide-react";
import type { Object3D } from "three";

import { ThreeDViewer } from "@/components/three-d/three-d-viewer";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  ApiError,
  cancelProjectThreeDJob,
  clarifyProjectThreeDJob,
  createProjectThreeDJob,
  getProjectThreeDAccess,
  getProjectThreeDArtifactLinks,
  listProjectThreeDJobs,
  listProjects,
} from "@/lib/api";
import type {
  Project,
  ThreeDAccess,
  ThreeDArtifactLinks,
  ThreeDGenerationJob,
} from "@/types";

const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
const TEXTURE_SIZES = [512, 1024, 2048, 4096] as const;
const ACTIVE_STATUSES = new Set(["queued", "running", "cancel_requested"]);
const KNOWN_STATUSES = new Set([
  "queued",
  "running",
  "cancel_requested",
  "needs_clarification",
  "completed",
  "failed",
  "cancelled",
]);
const PROJECT_STORAGE_KEY = "aionex.3d.project";

// Polling: one timer at a time, never faster than POLL_MIN_MS, slows down
// while nothing changes or requests fail, and pauses while the tab is hidden.
const POLL_MIN_MS = 4_000;
const POLL_MAX_MS = 30_000;
const POLL_ERROR_MAX_MS = 60_000;

/**
 * Access states the page can be in for the selected project. Each one maps to
 * an honest screen: nothing here reports success the backend did not confirm.
 */
type AccessState =
  | { kind: "loading" }
  | { kind: "ready"; access: ThreeDAccess }
  | { kind: "signedOut" }
  | { kind: "upgrade"; reason: "plan" | "billing" | "quota" }
  | { kind: "serviceDisabled" }
  | { kind: "providerUnavailable"; message: string }
  | { kind: "jurisdiction"; message: string }
  | { kind: "error"; message: string };

function readStoredProject(): string {
  try {
    return window.localStorage.getItem(PROJECT_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function writeStoredProject(value: string): void {
  try {
    window.localStorage.setItem(PROJECT_STORAGE_KEY, value);
  } catch {
    // Remembering the project is a convenience only.
  }
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function jobFingerprint(jobs: ThreeDGenerationJob[]): string {
  return jobs
    .map((job) => `${job.id}:${job.status}:${job.progress}:${job.stage}:${job.updated_at}`)
    .join("|");
}

function baseName(filename: string): string {
  const name = filename.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "-");
  return name || "aionex-model";
}

export function ThreeDClient() {
  const t = useTranslations("threeDStudio");
  const format = useFormatter();
  const locale = useLocale();
  const { isAuthenticated, isLoading } = useAuth();

  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectsError, setProjectsError] = useState("");
  const [projectId, setProjectId] = useState("");
  const [state, setState] = useState<AccessState>({ kind: "loading" });
  const [jobs, setJobs] = useState<ThreeDGenerationJob[]>([]);
  const [jobsError, setJobsError] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [links, setLinks] = useState<ThreeDArtifactLinks | null>(null);
  const [linksError, setLinksError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [clarificationFile, setClarificationFile] = useState<File | null>(null);
  const [textureSize, setTextureSize] = useState(1024);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [model, setModel] = useState<Object3D | null>(null);

  const pollDelay = useRef(POLL_MIN_MS);
  const pollTimer = useRef<number | null>(null);
  const pollInFlight = useRef(false);
  const lastFingerprint = useRef("");
  const activeProject = useRef("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const access = state.kind === "ready" ? state.access : null;
  const hasActiveJobs = useMemo(
    () => jobs.some((job) => ACTIVE_STATUSES.has(job.status)),
    [jobs],
  );
  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) || null,
    [jobs, selectedJobId],
  );

  // Data callbacks read the translator through a ref so a late translation
  // override never re-triggers project, job or link requests.
  const translate = useRef(t);
  useEffect(() => {
    translate.current = t;
  }, [t]);

  const statusLabel = useCallback(
    (status: string) => (KNOWN_STATUSES.has(status) ? t(`status.${status}`) : status),
    [t],
  );

  const describeError = useCallback(
    (cause: unknown, fallback: string): string => {
      const t = translate.current;
      if (cause instanceof ApiError) {
        switch (cause.code) {
          case "THREE_D_MONTHLY_QUOTA_REACHED":
            return t("errors.quota");
          case "THREE_D_CONCURRENCY_LIMIT":
            return t("errors.concurrency");
          case "THREE_D_ACCESS_NOT_GRANTED":
            return t("errors.notGranted");
          case "THREE_D_PROVIDERS_UNAVAILABLE":
          case "THREE_D_PROVIDER_CIRCUIT_OPEN":
            return t("errors.providerUnavailable");
          case "MEDIA_MAINTENANCE_CLOSED":
          case "MEDIA_MAINTENANCE_UNAVAILABLE":
            return t("errors.maintenance");
          case "THREE_D_HUNYUAN_OUTPUT_TERRITORY_BLOCKED":
          case "THREE_D_PROVIDER_NOT_PERMITTED":
            return t("errors.jurisdiction");
          case "THREE_D_IDEMPOTENCY_CONFLICT":
            return t("errors.duplicate");
          default:
            break;
        }
        if (cause.status === 401) return t("errors.sessionExpired");
        if (cause.status === 403) return t("errors.forbidden");
        if (cause.status === 410) return t("errors.expired");
        if (cause.status === 413) return t("errors.tooLarge");
        if (cause.status === 429) return t("errors.rateLimited");
      }
      return cause instanceof Error && cause.message ? cause.message : fallback;
    },
    [],
  );

  const classifyAccessError = useCallback(
    (cause: unknown): AccessState => {
      const t = translate.current;
      if (cause instanceof ApiError) {
        if (cause.status === 401) return { kind: "signedOut" };
        if (cause.status === 402) {
          return {
            kind: "upgrade",
            reason: cause.code === "THREE_D_MONTHLY_QUOTA_REACHED" ? "quota" : "billing",
          };
        }
        if (cause.status === 451) {
          return { kind: "jurisdiction", message: t("errors.jurisdiction") };
        }
        if (cause.status === 503) {
          return {
            kind: "providerUnavailable",
            message:
              cause.code === "MEDIA_MAINTENANCE_CLOSED" ||
              cause.code === "MEDIA_MAINTENANCE_UNAVAILABLE"
                ? t("errors.maintenance")
                : t("errors.providerUnavailable"),
          };
        }
      }
      return { kind: "error", message: describeError(cause, t("errors.load")) };
    },
    [describeError],
  );

  // Projects: 3D jobs are project-scoped on the backend.
  useEffect(() => {
    if (isLoading || !isAuthenticated) return;
    let cancelled = false;
    listProjects()
      .then((items) => {
        if (cancelled) return;
        setProjects(items);
        setProjectsError("");
        const stored = readStoredProject();
        const initial = items.find((item) => item.id === stored)?.id || items[0]?.id || "";
        setProjectId(initial);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        if (cause instanceof ApiError && cause.status === 401) {
          setState({ kind: "signedOut" });
          return;
        }
        setProjects([]);
        setProjectsError(describeError(cause, translate.current("errors.projects")));
      });
    return () => {
      cancelled = true;
    };
  }, [describeError, isAuthenticated, isLoading]);

  const loadJobs = useCallback(
    async (id: string): Promise<boolean> => {
      try {
        const next = await listProjectThreeDJobs(id, 20);
        // Ignore answers for a project the user has already switched away from.
        if (id !== activeProject.current) return false;
        setJobs(next);
        setJobsError("");
        const fingerprint = jobFingerprint(next);
        const changed = fingerprint !== lastFingerprint.current;
        lastFingerprint.current = fingerprint;
        return changed;
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 401) {
          setState({ kind: "signedOut" });
        }
        setJobsError(describeError(cause, translate.current("errors.jobs")));
        throw cause;
      }
    },
    [describeError],
  );

  const loadAll = useCallback(
    async (id: string, quiet = false) => {
      if (!quiet) {
        setState({ kind: "loading" });
        setError("");
      }
      const [accessResult] = await Promise.allSettled([
        getProjectThreeDAccess(id),
        loadJobs(id),
      ]);
      if (id !== activeProject.current) return;
      if (accessResult.status === "rejected") {
        setState(classifyAccessError(accessResult.reason));
        return;
      }
      const value = accessResult.value;
      setTextureSize((current) =>
        Math.min(current, value.max_texture_size || current),
      );
      if (!value.service_enabled) setState({ kind: "serviceDisabled" });
      else if (!value.eligible) setState({ kind: "upgrade", reason: "plan" });
      else setState({ kind: "ready", access: value });
    },
    [classifyAccessError, loadJobs],
  );

  useEffect(() => {
    if (!projectId) return;
    activeProject.current = projectId;
    writeStoredProject(projectId);
    setJobs([]);
    setSelectedJobId("");
    setLinks(null);
    setTermsAccepted(false);
    lastFingerprint.current = "";
    void loadAll(projectId);
  }, [loadAll, projectId]);

  // Bounded status polling. A chained timeout (not an interval) guarantees a
  // single request in flight; 401 stops polling because the api.ts refresh
  // gate already decided the session is gone.
  useEffect(() => {
    if (!projectId || !hasActiveJobs || state.kind === "signedOut") return;
    let stopped = false;

    const clear = () => {
      if (pollTimer.current !== null) {
        window.clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
    };
    const schedule = () => {
      clear();
      if (stopped || document.visibilityState === "hidden") return;
      pollTimer.current = window.setTimeout(() => void tick(), pollDelay.current);
    };
    const tick = async () => {
      pollTimer.current = null;
      if (stopped || document.visibilityState === "hidden") return;
      if (pollInFlight.current) {
        schedule();
        return;
      }
      pollInFlight.current = true;
      try {
        const changed = await loadJobs(projectId);
        pollDelay.current = changed
          ? POLL_MIN_MS
          : Math.min(POLL_MAX_MS, Math.round(pollDelay.current * 1.5));
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 401) {
          stopped = true;
          return;
        }
        pollDelay.current = Math.min(POLL_ERROR_MAX_MS, pollDelay.current * 2);
      } finally {
        pollInFlight.current = false;
      }
      schedule();
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        clear();
        return;
      }
      pollDelay.current = POLL_MIN_MS;
      clear();
      void tick();
    };

    pollDelay.current = POLL_MIN_MS;
    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      clear();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [hasActiveJobs, loadJobs, projectId, state.kind]);

  // Default the selection to the newest job.
  useEffect(() => {
    if (!jobs.length) {
      setSelectedJobId("");
      return;
    }
    setSelectedJobId((current) =>
      current && jobs.some((job) => job.id === current) ? current : jobs[0].id,
    );
  }, [jobs]);

  const selectedReady =
    selectedJob?.status === "completed" && selectedJob.has_artifact;

  const refreshLinks = useCallback(async () => {
    if (!projectId || !selectedJob) return;
    setLinksError("");
    try {
      setLinks(await getProjectThreeDArtifactLinks(projectId, selectedJob.id));
    } catch (cause) {
      setLinks(null);
      setLinksError(describeError(cause, translate.current("errors.links")));
    }
  }, [describeError, projectId, selectedJob]);

  useEffect(() => {
    setModel(null);
    setLinks(null);
    setLinksError("");
    if (!projectId || !selectedJobId || !selectedReady) return;
    let cancelled = false;
    getProjectThreeDArtifactLinks(projectId, selectedJobId)
      .then((value) => {
        if (!cancelled) setLinks(value);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setLinksError(describeError(cause, translate.current("errors.links")));
      });
    return () => {
      cancelled = true;
    };
  }, [describeError, projectId, selectedJobId, selectedReady]);

  useEffect(() => {
    if (!file) {
      setPreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function validateFile(value: File | null): value is File {
    if (!value || !access) return false;
    if (!(ACCEPTED_TYPES as readonly string[]).includes(value.type)) {
      setError(t("errors.invalidType"));
      return false;
    }
    if (value.size > access.max_input_megabytes * 1024 * 1024) {
      setError(t("errors.tooLargeLimit", { max: access.max_input_megabytes }));
      return false;
    }
    setError("");
    return true;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!access || !projectId || !validateFile(file)) return;
    if (!termsAccepted) {
      setError(t("errors.termsRequired"));
      return;
    }
    setBusy("create");
    setNotice("");
    try {
      const job = await createProjectThreeDJob(projectId, file, {
        textureSize,
        termsAccepted,
        termsVersion: access.third_party_terms_version,
      });
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      setSelectedJobId(job.id);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setTermsAccepted(false);
      setNotice(t("queued"));
      void loadAll(projectId, true);
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === "THREE_D_ACCESS_NOT_GRANTED") {
        setState({ kind: "upgrade", reason: "plan" });
      }
      setError(describeError(cause, t("errors.create")));
    } finally {
      setBusy(null);
    }
  }

  async function cancel(job: ThreeDGenerationJob) {
    if (!projectId) return;
    setBusy(`cancel:${job.id}`);
    try {
      const value = await cancelProjectThreeDJob(projectId, job.id);
      setJobs((current) => current.map((item) => (item.id === value.id ? value : item)));
    } catch (cause) {
      setError(describeError(cause, t("errors.cancel")));
    } finally {
      setBusy(null);
    }
  }

  async function clarify(job: ThreeDGenerationJob) {
    if (!access || !projectId || !validateFile(clarificationFile)) return;
    if (!termsAccepted) {
      setError(t("errors.termsRequired"));
      return;
    }
    setBusy(`clarify:${job.id}`);
    try {
      const value = await clarifyProjectThreeDJob(projectId, job.id, clarificationFile, {
        termsAccepted,
        termsVersion: access.third_party_terms_version,
      });
      setJobs((current) => current.map((item) => (item.id === value.id ? value : item)));
      setClarificationFile(null);
      setTermsAccepted(false);
    } catch (cause) {
      setError(describeError(cause, t("errors.clarify")));
    } finally {
      setBusy(null);
    }
  }

  async function exportObj() {
    if (!model) return;
    setBusy("obj");
    try {
      const { OBJExporter } = await import("three/examples/jsm/exporters/OBJExporter.js");
      const text = new OBJExporter().parse(model);
      const blob = new Blob([text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${baseName(links?.filename || "aionex-model")}.obj`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    } catch (cause) {
      setError(describeError(cause, t("errors.obj")));
    } finally {
      setBusy(null);
    }
  }

  const onModelChange = useCallback((value: Object3D | null) => setModel(value), []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const header = (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-3xl">
        <span className="eyebrow">
          <Box className="h-3.5 w-3.5" aria-hidden="true" /> {t("eyebrow")}
        </span>
        <h1 className="section-title mt-6">{t("title")}</h1>
        <p className="section-copy mt-4">{t("description")}</p>
      </div>
      {isAuthenticated && (
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/${locale}/projects`}
            className="portal-secondary-button inline-flex h-11 items-center gap-2 px-4 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
          >
            <FolderKanban className="h-4 w-4" aria-hidden="true" /> {t("projectsLink")}
          </Link>
          <Button
            variant="secondary"
            disabled={!projectId || state.kind === "loading"}
            onClick={() => projectId && void loadAll(projectId)}
          >
            <RefreshCw
              className={`h-4 w-4 ${state.kind === "loading" ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            {t("refresh")}
          </Button>
        </div>
      )}
    </div>
  );

  if (isLoading) {
    return (
      <section className="page-shell py-16 text-white">
        <div className="glass-panel flex min-h-52 items-center justify-center rounded-3xl" role="status" aria-label={t("loading")}>
          <LoaderCircle className="h-7 w-7 animate-spin text-crimson-200" aria-hidden="true" />
        </div>
      </section>
    );
  }

  if (!isAuthenticated || state.kind === "signedOut") {
    return (
      <section className="page-shell py-10 text-white sm:py-14">
        {header}
        <div className="glass-panel mt-8 rounded-3xl p-6 sm:p-8">
          <div className="flex items-start gap-3">
            <Lock className="mt-0.5 h-5 w-5 shrink-0 text-crimson-200" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold">{t("signedOut.title")}</h2>
              <p className="mt-2 text-sm leading-6 text-white/55">{t("signedOut.body")}</p>
              <div className="mt-5 flex flex-wrap gap-2">
                <Link
                  href={`/${locale}/login`}
                  className="portal-primary-button inline-flex h-11 items-center px-5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
                >
                  {t("signedOut.login")}
                </Link>
                <Link
                  href={`/${locale}/register`}
                  className="portal-secondary-button inline-flex h-11 items-center px-5 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
                >
                  {t("signedOut.register")}
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>
    );
  }

  const upgradePanel = (reason: "plan" | "billing" | "quota") => (
    <div className="glass-panel mt-6 rounded-3xl p-6 sm:p-8">
      <div className="flex items-start gap-3">
        <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-crimson-200" aria-hidden="true" />
        <div>
          <h2 className="text-lg font-semibold">{t(`upgrade.${reason}Title`)}</h2>
          <p className="mt-2 text-sm leading-6 text-white/55">{t(`upgrade.${reason}Body`)}</p>
          <Link
            href={`/${locale}/pricing`}
            className="portal-primary-button mt-5 inline-flex h-11 items-center px-5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
          >
            {t("upgrade.cta")}
          </Link>
        </div>
      </div>
    </div>
  );

  const unavailablePanel = (title: string, body: string) => (
    <div className="glass-panel mt-6 rounded-3xl p-6 sm:p-8" role="status">
      <div className="flex items-start gap-3">
        <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-crimson-200" aria-hidden="true" />
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          <p className="mt-2 text-sm leading-6 text-white/55">{body}</p>
          <p className="mt-2 text-xs leading-5 text-white/35">{t("unavailable.jobsStillVisible")}</p>
        </div>
      </div>
    </div>
  );

  let gate: ReactNode = null;
  if (state.kind === "upgrade") gate = upgradePanel(state.reason);
  else if (state.kind === "serviceDisabled")
    gate = unavailablePanel(t("unavailable.disabledTitle"), t("unavailable.disabledBody"));
  else if (state.kind === "providerUnavailable")
    gate = unavailablePanel(t("unavailable.providerTitle"), state.message);
  else if (state.kind === "jurisdiction")
    gate = unavailablePanel(t("unavailable.jurisdictionTitle"), state.message);
  else if (state.kind === "error")
    gate = <StatusMessage tone="error" className="mt-6">{state.message}</StatusMessage>;
  else if (access && access.monthly_remaining <= 0) gate = upgradePanel("quota");

  const termsCheckbox = (id: string) => (
    <div className="flex items-start gap-2 text-xs leading-5 text-white/55">
      <input
        id={id}
        type="checkbox"
        className="mt-1 h-4 w-4 accent-crimson-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
        checked={termsAccepted}
        onChange={(event) => setTermsAccepted(event.target.checked)}
      />
      <label htmlFor={id}>
        {t("terms.consent")}{" "}
        <a
          className="text-crimson-200 underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
          href={`/${locale}/legal/terms`}
          target="_blank"
          rel="noreferrer"
        >
          {t("terms.link")}
        </a>
      </label>
    </div>
  );

  const canCreate =
    state.kind === "ready" &&
    access !== null &&
    access.monthly_remaining > 0 &&
    access.active_jobs < access.max_concurrent_jobs;

  return (
    <section className="page-shell py-10 text-white sm:py-14">
      {header}

      {/* Project scope */}
      <div className="glass-panel mt-8 rounded-3xl p-5 sm:p-6">
        {projects === null ? (
          <p className="text-sm text-white/45" role="status">
            <LoaderCircle className="me-2 inline h-4 w-4 animate-spin" aria-hidden="true" />
            {t("loading")}
          </p>
        ) : projects.length === 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-sm font-semibold">{t("noProjects.title")}</p>
              <p className="mt-1 text-xs leading-5 text-white/50">{projectsError || t("noProjects.body")}</p>
            </div>
            <Link
              href={`/${locale}/projects`}
              className="portal-primary-button inline-flex h-11 items-center px-5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
            >
              {t("noProjects.cta")}
            </Link>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <div>
              <label htmlFor="three-d-project" className="field-label">
                {t("project.label")}
              </label>
              <select
                id="three-d-project"
                className="field-control"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
              >
                {projects.map((item) => (
                  <option key={item.id} value={item.id} className="bg-obsidian-900">
                    {item.name}
                  </option>
                ))}
              </select>
              <p className="mt-2 text-xs text-white/40">{t("project.hint")}</p>
            </div>
            {access && (
              <dl className="grid grid-cols-3 gap-3 text-center text-xs sm:min-w-[22rem]">
                <div className="rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2">
                  <dt className="text-white/40">{t("quota.remaining")}</dt>
                  <dd className="mt-1 text-sm font-semibold">
                    {access.monthly_remaining} / {access.monthly_quota}
                  </dd>
                </div>
                <div className="rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2">
                  <dt className="text-white/40">{t("quota.active")}</dt>
                  <dd className="mt-1 text-sm font-semibold">
                    {access.active_jobs} / {access.max_concurrent_jobs}
                  </dd>
                </div>
                <div className="rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2">
                  <dt className="text-white/40">{t("quota.plan")}</dt>
                  <dd className="mt-1 truncate text-sm font-semibold">{access.plan_code || "—"}</dd>
                </div>
              </dl>
            )}
          </div>
        )}
      </div>

      {projectId && state.kind === "loading" && (
        <div className="glass-panel mt-6 flex min-h-32 items-center justify-center rounded-3xl" role="status" aria-label={t("loading")}>
          <LoaderCircle className="h-6 w-6 animate-spin text-crimson-200" aria-hidden="true" />
        </div>
      )}

      {gate}
      {error && <StatusMessage tone="error" className="mt-6">{error}</StatusMessage>}
      {notice && <StatusMessage tone="success" className="mt-6">{notice}</StatusMessage>}

      {projectId && state.kind !== "loading" && (
        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
          <div className="space-y-6">
            {/* Create */}
            {access && state.kind === "ready" && (
              <form className="glass-panel rounded-3xl p-5 sm:p-6" onSubmit={(event) => void submit(event)} aria-labelledby="three-d-create-title">
                <h2 id="three-d-create-title" className="flex items-center gap-2 text-base font-semibold">
                  <Upload className="h-4 w-4 text-crimson-200" aria-hidden="true" /> {t("create.title")}
                </h2>
                <p className="mt-2 text-xs leading-5 text-white/45">{t("create.body")}</p>

                <div className="mt-5">
                  <label htmlFor="three-d-image" className="field-label">
                    {t("create.imageLabel")}
                  </label>
                  <input
                    ref={fileInputRef}
                    id="three-d-image"
                    type="file"
                    accept={ACCEPTED_TYPES.join(",")}
                    className="field-control text-xs"
                    aria-describedby="three-d-image-hint"
                    onChange={(event) => {
                      const next = event.target.files?.[0] || null;
                      setFile(next);
                      if (next) validateFile(next);
                    }}
                  />
                  <p id="three-d-image-hint" className="mt-2 text-xs text-white/40">
                    {t("create.imageHint", { max: access.max_input_megabytes })}
                  </p>
                  {previewUrl && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={previewUrl}
                      alt={t("create.previewAlt")}
                      className="mt-3 h-32 w-32 rounded-xl border border-white/[0.08] object-cover"
                    />
                  )}
                </div>

                <div className="mt-4">
                  <label htmlFor="three-d-texture" className="field-label">
                    {t("create.textureLabel")}
                  </label>
                  <select
                    id="three-d-texture"
                    className="field-control text-sm"
                    value={textureSize}
                    onChange={(event) => setTextureSize(Number(event.target.value))}
                  >
                    {TEXTURE_SIZES.filter((value) => value <= access.max_texture_size).map((value) => (
                      <option key={value} value={value} className="bg-obsidian-900">
                        {value} px
                      </option>
                    ))}
                  </select>
                </div>

                <dl className="mt-4 space-y-1.5 rounded-xl border border-white/[0.06] bg-black/20 p-3 text-xs leading-5 text-white/45">
                  <div className="flex flex-wrap gap-x-2">
                    <dt>{t("create.outputLabel")}</dt>
                    <dd className="text-white/70">{t("create.outputValue")}</dd>
                  </div>
                  <div className="flex flex-wrap gap-x-2">
                    <dt>{t("create.modelLabel")}</dt>
                    <dd className="text-white/70">
                      {access.model_disclosure.model} · {access.model_disclosure.license}
                    </dd>
                  </div>
                  <div className="flex flex-wrap gap-x-2">
                    <dt>{t("create.costLabel")}</dt>
                    <dd className="text-white/70">{t("create.costValue")}</dd>
                  </div>
                  {access.model_provider === "hunyuan3d" && (
                    <div>{t("create.hunyuanNoAffiliation", { operator: access.model_disclosure.operator })}</div>
                  )}
                  <div className="pt-1 text-white/35">{t("create.modelPolicy")}</div>
                </dl>

                <div className="mt-4 rounded-xl border border-dashed border-white/[0.1] p-3 text-xs leading-5 text-white/40">
                  <p className="font-semibold text-white/55">{t("create.textTitle")}</p>
                  <p className="mt-1">{t("create.textBody")}</p>
                </div>

                <div className="mt-4">{termsCheckbox("three-d-terms")}</div>

                {!canCreate && access.active_jobs >= access.max_concurrent_jobs && (
                  <p className="mt-3 text-xs text-white/45" role="status">{t("errors.concurrency")}</p>
                )}

                <Button
                  type="submit"
                  className="mt-5 w-full"
                  disabled={!canCreate || !file || !termsAccepted || busy === "create"}
                >
                  {busy === "create" ? (
                    <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Sparkles className="h-4 w-4" aria-hidden="true" />
                  )}
                  {busy === "create" ? t("create.submitting") : t("create.submit")}
                </Button>
              </form>
            )}

            {/* Jobs */}
            <div className="glass-panel rounded-3xl p-5 sm:p-6">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold">{t("jobs.title")}</h2>
                {hasActiveJobs && (
                  <span className="inline-flex items-center gap-1.5 text-xs text-white/40" role="status">
                    <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    {t("jobs.polling")}
                  </span>
                )}
              </div>
              {jobsError && <StatusMessage tone="error" className="mt-4">{jobsError}</StatusMessage>}
              {!jobs.length && !jobsError ? (
                <p className="mt-4 text-sm text-white/40">{t("jobs.empty")}</p>
              ) : (
                <ul className="mt-4 space-y-2" aria-label={t("jobs.title")}>
                  {jobs.map((job) => {
                    const selected = job.id === selectedJobId;
                    return (
                      <li key={job.id}>
                        <button
                          type="button"
                          onClick={() => setSelectedJobId(job.id)}
                          aria-pressed={selected}
                          className={`w-full rounded-2xl border px-4 py-3 text-start transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 ${
                            selected
                              ? "border-crimson-500/60 bg-crimson-500/[0.08]"
                              : "border-white/[0.08] bg-black/20 hover:border-white/20"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3 text-sm">
                            <span className="font-medium">{statusLabel(job.status)}</span>
                            <span className="text-xs text-white/40" dir="ltr">{job.progress}%</span>
                          </div>
                          <div
                            className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]"
                            role="progressbar"
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={Math.max(0, Math.min(100, job.progress))}
                            aria-label={statusLabel(job.status)}
                          >
                            <div
                              className="h-full rounded-full bg-gradient-to-r from-crimson-600 to-crimson-400"
                              style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }}
                            />
                          </div>
                          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-white/35">
                            <span>{format.dateTime(new Date(job.created_at), { dateStyle: "medium", timeStyle: "short" })}</span>
                            <span>{t("jobs.cost", { cost: job.estimated_cost_usd.toFixed(4) })}</span>
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>

          {/* Selected job: viewer + downloads */}
          <div className="glass-panel rounded-3xl p-5 sm:p-6">
            {!selectedJob ? (
              <div className="flex min-h-72 flex-col items-center justify-center text-center text-sm text-white/40">
                <Box className="h-8 w-8 text-white/20" aria-hidden="true" />
                <p className="mt-3">{t("viewer.empty")}</p>
              </div>
            ) : (
              <div>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold">{statusLabel(selectedJob.status)}</h2>
                    <p className="mt-1 text-xs text-white/40">
                      {t("viewer.stage", { stage: selectedJob.stage.replaceAll("_", " ") })} ·{" "}
                      {t("viewer.attempt", { attempt: selectedJob.attempts, total: selectedJob.max_attempts })}
                    </p>
                  </div>
                  {ACTIVE_STATUSES.has(selectedJob.status) && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy === `cancel:${selectedJob.id}` || selectedJob.status === "cancel_requested"}
                      onClick={() => void cancel(selectedJob)}
                    >
                      <Square className="h-3.5 w-3.5" aria-hidden="true" /> {t("viewer.cancel")}
                    </Button>
                  )}
                </div>

                {selectedJob.error_message && (
                  <StatusMessage tone={selectedJob.status === "failed" ? "error" : "info"} className="mt-4">
                    {selectedJob.error_message}
                  </StatusMessage>
                )}

                {selectedJob.status === "needs_clarification" && access && (
                  <div className="mt-4 space-y-3 rounded-2xl border border-white/[0.08] bg-black/20 p-4">
                    <label htmlFor="three-d-clarify" className="field-label">
                      {t("viewer.clarifyLabel")}
                    </label>
                    <input
                      id="three-d-clarify"
                      type="file"
                      accept={ACCEPTED_TYPES.join(",")}
                      className="field-control text-xs"
                      onChange={(event) => setClarificationFile(event.target.files?.[0] || null)}
                    />
                    {termsCheckbox("three-d-clarify-terms")}
                    <Button
                      disabled={!clarificationFile || !termsAccepted || busy === `clarify:${selectedJob.id}`}
                      onClick={() => void clarify(selectedJob)}
                    >
                      <RotateCcw className="h-4 w-4" aria-hidden="true" /> {t("viewer.clarifySubmit")}
                    </Button>
                  </div>
                )}

                {ACTIVE_STATUSES.has(selectedJob.status) && (
                  <div className="mt-4 flex min-h-56 flex-col items-center justify-center rounded-2xl border border-white/[0.08] bg-black/20 text-center text-sm text-white/45" role="status">
                    <LoaderCircle className="h-6 w-6 animate-spin text-crimson-200" aria-hidden="true" />
                    <p className="mt-3">{t("viewer.inProgress")}</p>
                  </div>
                )}

                {selectedJob.status === "completed" && !selectedJob.has_artifact && (
                  <StatusMessage className="mt-4">{t("viewer.noArtifact")}</StatusMessage>
                )}

                {selectedReady && (
                  <div className="mt-4">
                    {linksError && <StatusMessage tone="error">{linksError}</StatusMessage>}
                    {!links && !linksError && (
                      <p className="text-xs text-white/40" role="status">
                        <LoaderCircle className="me-2 inline h-4 w-4 animate-spin" aria-hidden="true" />
                        {t("viewer.loadingLinks")}
                      </p>
                    )}
                    {links && (
                      <>
                        <ThreeDViewer
                          url={links.view_url}
                          className="mt-0"
                          heightClassName="h-80 sm:h-[28rem]"
                          onModelChange={onModelChange}
                          labels={{
                            error: t("viewer.previewError"),
                            viewport: t("viewer.viewport"),
                            reset: t("viewer.reset"),
                            zoomIn: t("viewer.zoomIn"),
                            zoomOut: t("viewer.zoomOut"),
                            loading: t("viewer.loadingModel"),
                          }}
                        />
                        <p className="mt-2 text-[11px] text-white/35">{t("viewer.controlsHint")}</p>
                        <div className="mt-4 flex flex-wrap gap-2">
                          <a
                            href={links.download_url}
                            rel="noreferrer"
                            className="portal-primary-button inline-flex h-11 items-center gap-2 px-5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
                          >
                            <Download className="h-4 w-4" aria-hidden="true" />
                            {t("download.glb")}
                          </a>
                          <Button variant="secondary" disabled={!model || busy === "obj"} onClick={() => void exportObj()}>
                            <FileDown className="h-4 w-4" aria-hidden="true" />
                            {t("download.obj")}
                          </Button>
                          <Button variant="ghost" onClick={() => void refreshLinks()}>
                            <RefreshCw className="h-4 w-4" aria-hidden="true" />
                            {t("download.refresh")}
                          </Button>
                        </div>
                        <ul className="mt-3 space-y-1 text-[11px] leading-5 text-white/35">
                          <li>
                            {links.filename} · <span dir="ltr">{formatBytes(links.size_bytes)}</span>
                          </li>
                          <li>{t("download.objNote")}</li>
                          <li>{t("download.expiry", { minutes: Math.max(1, Math.round(links.expires_in / 60)) })}</li>
                          <li className="break-all">
                            <ShieldCheck className="me-1 inline h-3 w-3" aria-hidden="true" />
                            <span dir="ltr">SHA-256 {links.sha256}</span>
                          </li>
                        </ul>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
