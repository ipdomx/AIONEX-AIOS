"use client";

import {
  BookOpen,
  CheckCircle2,
  Download,
  FileArchive,
  GraduationCap,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  XCircle,
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
import {
  createAcademyCourse,
  createAcademyCoursePackage,
  downloadAcademyCoursePackage,
  listAcademyCoursePackages,
  listAcademyCourses,
  reviewAcademyCoursePackage,
  type AcademyCourse,
  type AcademyCoursePackage,
} from "@/lib/academy-api";

const activePackageStatuses = new Set(["queued", "building"]);
const supportedLocales = ["ar", "en", "fr", "de", "es", "tr"];

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

function formatBytes(value: number | null): string {
  if (!value) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function packageMap(
  pairs: ReadonlyArray<readonly [string, AcademyCoursePackage[]]>,
): Record<string, AcademyCoursePackage[]> {
  return Object.fromEntries(pairs);
}

export function AcademyClient() {
  const t = useTranslations("academyUser");
  const locale = useLocale();
  const router = useRouter();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [courses, setCourses] = useState<AcademyCourse[]>([]);
  const [packages, setPackages] = useState<Record<string, AcademyCoursePackage[]>>({});
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const permissions = useMemo(() => new Set(user?.permissions || []), [user]);
  const hasAll = permissions.has("*");
  const canRead = hasAll || permissions.has("academy:read");
  const canWrite = hasAll || permissions.has("academy:write");
  const canAssess = hasAll || permissions.has("academy:assess");
  const nonFreePlan =
    user?.role !== "Free User" &&
    (user?.organization.plan || "").toLowerCase() !== "free";

  const allPackages = useMemo(
    () => Object.values(packages).flat(),
    [packages],
  );
  const activePackageIds = useMemo(
    () => allPackages.filter((item) => activePackageStatuses.has(item.status)).map((item) => item.id),
    [allPackages],
  );

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async (quiet = false) => {
    if (!isAuthenticated || !user || !nonFreePlan || !canRead) {
      if (!quiet) setLoading(false);
      return;
    }
    if (!quiet) {
      setLoading(true);
      setError("");
    }
    try {
      const rows = await listAcademyCourses();
      const pairs = await Promise.all(
        rows.map(async (course) => [course.id, await listAcademyCoursePackages(course.id)] as const),
      );
      setCourses(rows);
      setPackages(packageMap(pairs));
      setSelectedCourseId((current) =>
        current && rows.some((item) => item.id === current)
          ? current
          : rows[0]?.id || "",
      );
    } catch (cause) {
      if (!quiet) setError(errorText(cause, t("loadError")));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [canRead, isAuthenticated, nonFreePlan, t, user]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!activePackageIds.length) return;
    const timer = window.setInterval(() => void load(true), 3000);
    return () => window.clearInterval(timer);
  }, [activePackageIds.length, load]);

  async function submitCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("course");
    setError("");
    setMessage("");
    try {
      const course = await createAcademyCourse({
        code: String(values.get("code") || "").trim(),
        title: String(values.get("title") || "").trim(),
        description: String(values.get("description") || "").trim() || null,
        competencies: String(values.get("competencies") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
          .slice(0, 50),
        passing_score: Number(values.get("passing_score") || 80),
      });
      setCourses((current) => [course, ...current]);
      setPackages((current) => ({ ...current, [course.id]: [] }));
      setSelectedCourseId(course.id);
      form.reset();
      setMessage(t("courseCreated", { name: course.title }));
    } catch (cause) {
      setError(errorText(cause, t("courseCreateError")));
    } finally {
      setBusy(null);
    }
  }

  async function submitPackage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite || !selectedCourseId) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    const idempotencyKey =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? `vip-course-${crypto.randomUUID()}`
        : `vip-course-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setBusy("package");
    setError("");
    setMessage("");
    try {
      const item = await createAcademyCoursePackage(selectedCourseId, {
        idempotency_key: idempotencyKey,
        domain: String(values.get("domain") || "").trim(),
        audience: String(values.get("audience") || "").trim(),
        locales: supportedLocales,
        module_count: Number(values.get("module_count") || 2),
        lessons_per_module: Number(values.get("lessons_per_module") || 2),
        citations: [],
      });
      setPackages((current) => ({
        ...current,
        [selectedCourseId]: [item, ...(current[selectedCourseId] || [])],
      }));
      setMessage(t("packageQueued"));
      form.reset();
    } catch (cause) {
      setError(errorText(cause, t("packageCreateError")));
    } finally {
      setBusy(null);
    }
  }

  async function review(item: AcademyCoursePackage, approved: boolean) {
    if (!canAssess) return;
    const notes = window.prompt(t(approved ? "approvePrompt" : "rejectPrompt"), "") ?? "";
    setBusy(item.id);
    setError("");
    setMessage("");
    try {
      const updated = await reviewAcademyCoursePackage(item.id, { approved, notes });
      setPackages((current) => ({
        ...current,
        [item.course_id]: (current[item.course_id] || []).map((row) =>
          row.id === updated.id ? updated : row,
        ),
      }));
      setMessage(approved ? t("approved") : t("rejected"));
    } catch (cause) {
      setError(errorText(cause, t("reviewError")));
    } finally {
      setBusy(null);
    }
  }

  async function download(item: AcademyCoursePackage) {
    setBusy(item.id);
    setError("");
    try {
      const { blob, filename } = await downloadAcademyCoursePackage(item.id);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename || `course-${item.course_id}-v${item.version}.zip`;
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

  if (isLoading || (!isAuthenticated && !isLoading)) {
    return (
      <section className="page-shell py-16 text-white">
        <div className="glass-panel flex min-h-52 items-center justify-center rounded-3xl">
          <LoaderCircle className="h-7 w-7 animate-spin text-electric-200" />
        </div>
      </section>
    );
  }

  if (!nonFreePlan) {
    return (
      <section className="page-shell py-12 text-white sm:py-16">
        <div className="glass-panel mx-auto max-w-3xl rounded-3xl p-7 sm:p-10">
          <GraduationCap className="h-8 w-8 text-electric-200" />
          <h1 className="mt-5 text-2xl font-semibold">{t("planTitle")}</h1>
          <p className="mt-3 text-sm leading-7 text-white/45">{t("planCopy")}</p>
          <Button className="mt-6" variant="secondary" onClick={() => router.push(`/${locale}/studio`)}>
            {t("backStudio")}
          </Button>
        </div>
      </section>
    );
  }

  if (!canRead) {
    return (
      <section className="page-shell py-12 text-white sm:py-16">
        <div className="glass-panel mx-auto max-w-3xl rounded-3xl p-7 sm:p-10">
          <ShieldCheck className="h-8 w-8 text-electric-200" />
          <h1 className="mt-5 text-2xl font-semibold">{t("permissionTitle")}</h1>
          <p className="mt-3 text-sm leading-7 text-white/45">{t("permissionCopy")}</p>
          <Button className="mt-6" variant="secondary" onClick={() => router.push(`/${locale}/studio`)}>
            {t("backStudio")}
          </Button>
        </div>
      </section>
    );
  }

  return (
    <section className="page-shell py-10 text-white sm:py-14">
      <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
        <div className="max-w-3xl">
          <span className="eyebrow">
            <GraduationCap className="h-3.5 w-3.5" /> {t("eyebrow")}
          </span>
          <h1 className="section-title mt-6">{t("title")}</h1>
          <p className="section-copy mt-4">{t("description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => router.push(`/${locale}/studio`)}>
            <Sparkles className="h-4 w-4" /> {t("backStudio")}
          </Button>
          <Button variant="secondary" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> {t("refresh")}
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

      {error && <StatusMessage tone="error" className="mt-8">{error}</StatusMessage>}
      {message && <StatusMessage className="mt-8">{message}</StatusMessage>}

      {canWrite && (
        <div className="mt-8 grid gap-6 xl:grid-cols-2">
          <form className="glass-panel rounded-3xl p-5 sm:p-7" onSubmit={submitCourse}>
            <div className="flex items-center gap-3">
              <Plus className="h-5 w-5 text-electric-200" />
              <h2 className="text-lg font-semibold">{t("createCourse")}</h2>
            </div>
            <div className="mt-6 grid gap-4 sm:grid-cols-2">
              <input className="field-control" name="code" minLength={2} maxLength={120} placeholder={t("code")} required />
              <input className="field-control" name="title" minLength={2} maxLength={240} placeholder={t("courseTitle")} required />
              <textarea className="field-control min-h-28 resize-y sm:col-span-2" name="description" maxLength={20000} placeholder={t("courseDescription")} />
              <input className="field-control" name="competencies" placeholder={t("competencies")} />
              <input className="field-control" name="passing_score" type="number" min={0} max={100} defaultValue={80} aria-label={t("passingScore")} />
            </div>
            <Button className="mt-5" type="submit" disabled={busy === "course"}>
              {busy === "course" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {t("createCourse")}
            </Button>
          </form>

          <form className="glass-panel rounded-3xl p-5 sm:p-7" onSubmit={submitPackage}>
            <div className="flex items-center gap-3">
              <FileArchive className="h-5 w-5 text-electric-200" />
              <h2 className="text-lg font-semibold">{t("buildPackage")}</h2>
            </div>
            <div className="mt-6 grid gap-4 sm:grid-cols-2">
              <select className="field-control sm:col-span-2" value={selectedCourseId} onChange={(event) => setSelectedCourseId(event.target.value)} required>
                {!courses.length && <option value="">{t("noCourses")}</option>}
                {courses.map((course) => <option className="bg-ink-800" value={course.id} key={course.id}>{course.title}</option>)}
              </select>
              <input className="field-control" name="domain" minLength={2} maxLength={240} placeholder={t("domain")} required />
              <input className="field-control" name="audience" minLength={2} maxLength={240} placeholder={t("audience")} required />
              <label className="text-xs text-white/45">{t("modules")}
                <input className="field-control mt-2" name="module_count" type="number" min={1} max={8} defaultValue={2} />
              </label>
              <label className="text-xs text-white/45">{t("lessonsPerModule")}
                <input className="field-control mt-2" name="lessons_per_module" type="number" min={1} max={8} defaultValue={2} />
              </label>
            </div>
            <p className="mt-4 text-xs leading-6 text-white/35">{t("sixLocalePackage")}</p>
            <Button className="mt-5" type="submit" disabled={busy === "package" || !selectedCourseId}>
              {busy === "package" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {t("queuePackage")}
            </Button>
          </form>
        </div>
      )}

      <div className="mt-10">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{t("courseLibrary")}</h2>
            <p className="mt-1 text-xs text-white/35">{t("courseLibraryCopy")}</p>
          </div>
          <span className="rounded-full border border-white/[0.08] px-3 py-1 text-xs text-white/45">{courses.length}</span>
        </div>

        {!courses.length && !loading && (
          <div className="mt-5 rounded-3xl border border-dashed border-white/10 p-8 text-center text-sm text-white/40">{t("emptyCourses")}</div>
        )}

        <div className="mt-5 grid gap-5 xl:grid-cols-2">
          {courses.map((course) => (
            <article className="glass-panel rounded-3xl p-5 sm:p-6" key={course.id}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-xs text-electric-200"><BookOpen className="h-3.5 w-3.5" /> {course.code}</div>
                  <h3 className="mt-2 text-lg font-semibold">{course.title}</h3>
                  {course.description && <p className="mt-2 text-xs leading-6 text-white/40">{course.description}</p>}
                </div>
                <span className="rounded-full border border-white/[0.08] px-2.5 py-1 text-[11px] text-white/45">{course.status}</span>
              </div>
              <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-white/35">
                <span>{t("passing", { score: course.passing_score })}</span>
                <span>·</span>
                <span>{t("version", { version: course.version })}</span>
                {course.competencies.length > 0 && <><span>·</span><span>{course.competencies.slice(0, 3).join(" · ")}</span></>}
              </div>

              <div className="mt-5 space-y-3 border-t border-white/[0.06] pt-5">
                {(packages[course.id] || []).length === 0 && (
                  <p className="text-xs text-white/35">{t("noPackages")}</p>
                )}
                {(packages[course.id] || []).map((item) => (
                  <div className="rounded-2xl border border-white/[0.06] bg-black/10 p-4" key={item.id}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold">{t("packageVersion", { version: item.version })}</p>
                        <p className="mt-1 text-[11px] text-white/35">{t("lessons", { count: item.lesson_count })} · {formatBytes(item.archive_bytes)}</p>
                      </div>
                      <span className="rounded-full border border-white/[0.08] px-2 py-1 text-[10px] text-white/45">{item.status}</span>
                    </div>
                    {activePackageStatuses.has(item.status) && (
                      <div className="mt-3 flex items-center gap-2 text-xs text-electric-200"><LoaderCircle className="h-3.5 w-3.5 animate-spin" /> {t("building")}</div>
                    )}
                    {item.archive_sha256 && <p className="mt-3 truncate font-mono text-[10px] text-white/25">SHA-256 {item.archive_sha256}</p>}
                    {item.error_code && <p className="mt-3 text-xs text-red-300/80">{item.error_code}</p>}
                    <div className="mt-4 flex flex-wrap gap-2">
                      {item.download_ready && (
                        <Button size="sm" disabled={busy === item.id} onClick={() => void download(item)}>
                          <Download className="h-3.5 w-3.5" /> {t("download")}
                        </Button>
                      )}
                      {canAssess && item.status === "review_pending" && (
                        <>
                          <Button size="sm" variant="secondary" disabled={busy === item.id} onClick={() => void review(item, true)}>
                            <CheckCircle2 className="h-3.5 w-3.5" /> {t("approve")}
                          </Button>
                          <Button size="sm" variant="danger" disabled={busy === item.id} onClick={() => void review(item, false)}>
                            <XCircle className="h-3.5 w-3.5" /> {t("reject")}
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
