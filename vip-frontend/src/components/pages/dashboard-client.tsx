"use client";

import {
  ArrowUpRight,
  CreditCard,
  FolderKanban,
  Gauge,
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
import { getFreeTierStatus, listProjects } from "@/lib/api";
import type { FreeTierStatus, Project } from "@/types";

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

export function DashboardClient() {
  const t = useTranslations("dashboard");
  const projectsT = useTranslations("projects");
  const locale = useLocale();
  const router = useRouter();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [quota, setQuota] = useState<FreeTierStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [projectItems, quotaStatus] = await Promise.all([
        listProjects(),
        getFreeTierStatus(),
      ]);
      setProjects(projectItems);
      setQuota(quotaStatus);
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
            className="h-8 w-8 animate-spin text-electric-200"
            aria-label={t("loading")}
          />
        </div>
      </section>
    );
  }

  const usedProjects =
    quotaValue(quota, "usage", "projects") ?? projects.length;
  const projectLimit = quotaValue(quota, "limits", "projects");
  const remainingMessages = quotaValue(quota, "remaining", "user_messages");
  const remainingResponses = quotaValue(
    quota,
    "remaining",
    "assistant_responses",
  );

  const metrics = [
    {
      label: t("projectsUsed"),
      value:
        projectLimit === null
          ? String(usedProjects)
          : `${usedProjects} / ${projectLimit}`,
      icon: FolderKanban,
    },
    {
      label: t("messagesRemaining"),
      value:
        remainingMessages === null
          ? "—"
          : remainingMessages.toLocaleString(locale),
      icon: MessageSquareText,
    },
    {
      label: t("responsesRemaining"),
      value:
        remainingResponses === null
          ? "—"
          : remainingResponses.toLocaleString(locale),
      icon: Gauge,
    },
    {
      label: t("accountRole"),
      value: user?.role || "—",
      icon: ShieldCheck,
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
                  className="h-5 w-5 text-electric-200"
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
                  className="inline-flex items-center gap-2 text-sm font-semibold text-electric-200 hover:text-electric-100"
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
                    className="h-4 w-4 text-electric-200"
                    aria-hidden="true"
                  />
                </Link>
                <Link
                  href={`/${locale}/billing`}
                  className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                >
                  {t("manageBilling")}
                  <CreditCard
                    className="h-4 w-4 text-electric-200"
                    aria-hidden="true"
                  />
                </Link>
                <Link
                  href={`/${locale}/profile`}
                  className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                >
                  {t("accountSettings")}
                  <UserRound
                    className="h-4 w-4 text-electric-200"
                    aria-hidden="true"
                  />
                </Link>
                <Link
                  href={`/${locale}/contact`}
                  className="inline-flex min-h-12 items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white"
                >
                  {t("contactSupport")}
                  <MessageSquareText
                    className="h-4 w-4 text-electric-200"
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
