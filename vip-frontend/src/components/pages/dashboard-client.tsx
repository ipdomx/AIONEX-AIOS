"use client";

import {
  ArrowUpRight,
  Bell,
  CreditCard,
  FolderKanban,
  Gauge,
  HardDrive,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import { getFreeTierStatus, getSecurityLabAccess, listProjects } from "@/lib/api";
import type { FreeTierStatus, Project, SecurityLabAccess } from "@/types";

const projectStatuses = new Set([
  "planning",
  "active",
  "in_progress",
  "completed",
  "paused",
  "cancelled",
]);

function quotaValue(
  status: FreeTierStatus | null,
  group: "limits" | "usage" | "remaining",
  key: string,
): number | null {
  const value = status?.[group]?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// The API sends `null` for a limit the plan leaves open (unlimited).
function isUnlimited(status: FreeTierStatus | null, key: string): boolean {
  return Boolean(status?.limits && key in status.limits && status.limits[key] === null);
}

function formatBytes(value: number, locale: string): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toLocaleString(locale, { maximumFractionDigits: unit < 2 ? 0 : 1 })} ${units[unit]}`;
}

export function DashboardClient() {
  const t = useTranslations("dashboard");
  const projectsT = useTranslations("projects");
  const locale = useLocale();
  const router = useRouter();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [quota, setQuota] = useState<FreeTierStatus | null>(null);
  const [securityAccess, setSecurityAccess] = useState<SecurityLabAccess | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [projectItems, quotaStatus, securityStatus] = await Promise.all([
        listProjects(),
        getFreeTierStatus(),
        getSecurityLabAccess().catch(() => null),
      ]);
      setProjects(projectItems);
      setQuota(quotaStatus);
      setSecurityAccess(securityStatus);
    } catch {
      setError(t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (isAuthenticated) void load();
  }, [isAuthenticated, load]);

  const recentProjects = useMemo(
    () =>
      [...projects]
        .sort(
          (left, right) =>
            new Date(right.updated_at).getTime() -
            new Date(left.updated_at).getTime(),
        )
        .slice(0, 5),
    [projects],
  );

  if (isLoading || (!isAuthenticated && !error)) {
    return (
      <section className="section-pad">
        <div className="page-shell flex min-h-[45vh] items-center justify-center">
          <LoaderCircle
            className="h-8 w-8 animate-spin text-crimson-200"
            aria-label={t("loading")}
          />
        </div>
      </section>
    );
  }

  const usedProjects =
    quotaValue(quota, "usage", "projects") ?? projects.length;
  const projectLimit = quotaValue(quota, "limits", "projects");
  const remainingValue = (key: string): string => {
    if (isUnlimited(quota, key)) return t("unlimited");
    const remaining = quotaValue(quota, "remaining", key);
    const limit = quotaValue(quota, "limits", key);
    if (remaining === null) return "—";
    return limit === null
      ? remaining.toLocaleString(locale)
      : `${remaining.toLocaleString(locale)} / ${limit.toLocaleString(locale)}`;
  };
  const usedStorage = quotaValue(quota, "usage", "storage_bytes");
  const storageLimit = quotaValue(quota, "limits", "storage_bytes");
  const storageValue =
    usedStorage === null
      ? "—"
      : isUnlimited(quota, "storage_bytes") || storageLimit === null
        ? `${formatBytes(usedStorage, locale)} · ${t("unlimited")}`
        : `${formatBytes(usedStorage, locale)} / ${formatBytes(storageLimit, locale)}`;
  const periodEnd = quota?.period_ends_at
    ? new Date(quota.period_ends_at).toLocaleDateString(locale, {
        day: "numeric",
        month: "long",
      })
    : null;

  const metrics = [
    {
      label: t("projectsUsed"),
      value: isUnlimited(quota, "projects")
        ? `${usedProjects} · ${t("unlimited")}`
        : projectLimit === null
          ? String(usedProjects)
          : `${usedProjects} / ${projectLimit}`,
      icon: FolderKanban,
    },
    {
      label: t("messagesRemaining"),
      value: remainingValue("user_messages"),
      icon: MessageSquareText,
    },
    {
      label: t("responsesRemaining"),
      value: remainingValue("assistant_responses"),
      icon: Gauge,
    },
    {
      label: t("storageUsed"),
      value: storageValue,
      icon: HardDrive,
    },
  ];

  return (
    <section className="section-pad">
      <div className="page-shell">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <span className="eyebrow">{t("eyebrow")}</span>
            <h1 className="section-title mt-6">
              {t("welcome", { name: user?.name || "" })}
            </h1>
            <p className="section-copy mt-4">{t("description")}</p>
            {quota && (
              <p className="mt-3 text-sm text-white/60">
                {t("planLine", {
                  plan: quota.plan_name || quota.plan || "—",
                  role: user?.role || "—",
                })}
                {periodEnd ? ` · ${t("resetsOn", { date: periodEnd })}` : ""}
              </p>
            )}
          </div>
          <Button
            variant="secondary"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw
              className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            {t("refresh")}
          </Button>
        </div>

        {error && (
          <StatusMessage tone="error" className="mt-7">
            {error}
          </StatusMessage>
        )}

        <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map(({ label, value, icon: Icon }) => (
            <Card key={label}>
              <CardContent>
                <Icon
                  className="h-5 w-5 text-crimson-200"
                  aria-hidden="true"
                />
                <p className="mt-5 text-xs uppercase tracking-[0.14em] text-white/35">
                  {label}
                </p>
                <p className="mt-2 break-words text-2xl font-semibold text-white">
                  {value}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-[1.35fr_.65fr]">
          <Card>
            <CardContent>
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold">
                    {t("recentProjects")}
                  </h2>
                  <p className="mt-2 text-sm text-white/40">
                    {t("recentProjectsCopy")}
                  </p>
                </div>
                <Link
                  href={`/${locale}/projects`}
                  className="inline-flex items-center gap-2 text-sm font-semibold text-crimson-200 hover:text-crimson-100"
                >
                  {t("viewProjects")}
                  <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </div>

              <div className="mt-6 space-y-3">
                {loading && !projects.length ? (
                  <div className="flex min-h-32 items-center justify-center text-white/40">
                    <LoaderCircle
                      className="me-2 h-5 w-5 animate-spin"
                      aria-hidden="true"
                    />
                    {t("loading")}
                  </div>
                ) : recentProjects.length ? (
                  recentProjects.map((project) => (
                    <div
                      key={project.id}
                      className="grid gap-3 rounded-2xl border border-white/[0.07] bg-black/15 p-4 sm:grid-cols-[1fr_auto] sm:items-center"
                    >
                      <div className="min-w-0">
                        <h3 className="truncate font-semibold text-white">
                          {project.name}
                        </h3>
                        <p className="mt-1 truncate text-xs text-white/35">
                          {project.workspace}
                        </p>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-white/45">
                        <span>
                          {projectsT("progress", { value: project.progress })}
                        </span>
                        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1">
                          {projectStatuses.has(project.status)
                            ? projectsT(`status.${project.status}`)
                            : project.status}
                        </span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-white/10 px-5 py-10 text-center">
                    <p className="font-semibold">{t("noProjects")}</p>
                    <p className="mt-2 text-sm text-white/40">
                      {t("noProjectsCopy")}
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <h2 className="text-xl font-semibold">{t("quickActions")}</h2>
              <div className="mt-6 grid gap-3">
                <Link
                  href={`/${locale}/projects`}
                  className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                >
                  {t("manageProjects")}
                  <FolderKanban
                    className="h-4 w-4 text-crimson-200"
                    aria-hidden="true"
                  />
                </Link>
                <Link
                  href={`/${locale}/billing`}
                  className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                >
                  {t("manageBilling")}
                  <CreditCard
                    className="h-4 w-4 text-crimson-200"
                    aria-hidden="true"
                  />
                </Link>
                {securityAccess?.enabled && securityAccess.granted && (
                  <Link
                    href={`/${locale}/security-lab`}
                    className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                  >
                    {t("securityLab")}
                    <ShieldCheck
                      className="h-4 w-4 text-crimson-200"
                      aria-hidden="true"
                    />
                  </Link>
                )}
                <Link
                  href={`/${locale}/profile`}
                  className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                >
                  {t("accountSettings")}
                  <UserRound
                    className="h-4 w-4 text-crimson-200"
                    aria-hidden="true"
                  />
                </Link>
                <Link
                  href={`/${locale}/notifications`}
                  className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                >
                  {t("notifications")}
                  <Bell
                    className="h-4 w-4 text-crimson-200"
                    aria-hidden="true"
                  />
                </Link>
                <Link
                  href={`/${locale}/support`}
                  className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                >
                  {t("contactSupport")}
                  <MessageSquareText
                    className="h-4 w-4 text-crimson-200"
                    aria-hidden="true"
                  />
                </Link>
              </div>
              <p className="mt-6 text-xs leading-6 text-white/35">
                {t("organization", { name: user?.organization.name || "—" })}
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </section>
  );
}
