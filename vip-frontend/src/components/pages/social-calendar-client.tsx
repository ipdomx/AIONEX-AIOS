"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  CalendarDays,
  CircleX,
  SquarePen,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  LoaderCircle,
  Lock,
  RefreshCw,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import { cancelSocialPost, deleteSocialPost, getSocialPost, listSocialPosts } from "@/lib/api";
import type { SocialPost } from "@/types";

import {
  POST_STATUS_TONE,
  PlatformGlyph,
  TARGET_STATUS_TONE,
  apiErrorKey,
  issueKey,
  safePermalink,
} from "./social-publishing-shared";

type View = "month" | "week";
const DAY_MS = 86400000;

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

/** Visible grid: weeks start on the locale's first weekday (Saturday for ar). */
function visibleRange(view: View, anchor: Date, weekStart: number): { start: Date; end: Date } {
  const base = view === "month" ? new Date(anchor.getFullYear(), anchor.getMonth(), 1) : startOfDay(anchor);
  const offset = (base.getDay() - weekStart + 7) % 7;
  const start = addDays(base, -offset);
  if (view === "week") return { start, end: addDays(start, 7) };
  const monthEnd = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1);
  const days = Math.ceil((monthEnd.getTime() - start.getTime()) / DAY_MS);
  return { start, end: addDays(start, Math.ceil(days / 7) * 7) };
}

function postDate(post: SocialPost): Date | null {
  const value = post.published_at || post.scheduled_at;
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function SocialCalendarClient() {
  const t = useTranslations("socialPublishing");
  const format = useFormatter();
  const locale = useLocale();
  const { isAuthenticated, isLoading } = useAuth();
  const weekStart = locale === "ar" ? 6 : locale === "en" ? 0 : 1;

  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()));
  const [items, setItems] = useState<SocialPost[]>([]);
  const [drafts, setDrafts] = useState<SocialPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<SocialPost | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const range = useMemo(() => visibleRange(view, anchor, weekStart), [view, anchor, weekStart]);
  const errorText = useCallback((cause: unknown) => t(`errors.${apiErrorKey(cause)}`), [t]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [calendar, recent] = await Promise.all([
        listSocialPosts({ start: range.start.toISOString(), end: range.end.toISOString() }),
        listSocialPosts(),
      ]);
      setItems(calendar.items);
      setDrafts(recent.items.filter((item) => item.status === "draft"));
      setError("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setLoading(false);
    }
  }, [range, errorText]);

  useEffect(() => {
    if (isAuthenticated) void load();
  }, [isAuthenticated, load]);

  const byDay = useMemo(() => {
    const map = new Map<string, SocialPost[]>();
    for (const post of items) {
      const date = postDate(post);
      if (!date) continue;
      const key = dayKey(date);
      map.set(key, [...(map.get(key) || []), post]);
    }
    for (const list of map.values()) list.sort((a, b) => (postDate(a)?.getTime() || 0) - (postDate(b)?.getTime() || 0));
    return map;
  }, [items]);

  const days = useMemo(() => {
    const list: Date[] = [];
    for (let day = range.start; day.getTime() < range.end.getTime(); day = addDays(day, 1)) list.push(day);
    return list;
  }, [range]);

  function move(step: number) {
    setAnchor((current) =>
      view === "month" ? new Date(current.getFullYear(), current.getMonth() + step, 1) : addDays(current, 7 * step),
    );
  }

  async function openDetail(postId: string) {
    setBusy(`open:${postId}`);
    try {
      setDetail(await getSocialPost(postId));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  async function cancel(post: SocialPost) {
    setBusy(`cancel:${post.id}`);
    try {
      setDetail(await cancelSocialPost(post.id));
      await load();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  async function remove(post: SocialPost) {
    setBusy(`delete:${post.id}`);
    try {
      await deleteSocialPost(post.id);
      setDetail(null);
      await load();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  const title =
    view === "month"
      ? format.dateTime(anchor, { month: "long", year: "numeric" })
      : `${format.dateTime(range.start, { day: "numeric", month: "short" })} – ${format.dateTime(addDays(range.end, -1), {
          day: "numeric",
          month: "short",
          year: "numeric",
        })}`;
  const today = dayKey(new Date());

  const header = (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-3xl">
        <span className="eyebrow">
          <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" /> {t("calendar.eyebrow")}
        </span>
        <h1 className="section-title mt-6">{t("calendar.title")}</h1>
        <p className="section-copy mt-4">{t("calendar.description")}</p>
      </div>
      <Link
        href={`/${locale}/social/compose`}
        className="portal-primary-button inline-flex h-11 items-center gap-2 px-5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
      >
        <SquarePen className="h-4 w-4" aria-hidden="true" />
        {t("nav.compose")}
      </Link>
    </div>
  );

  if (isLoading) {
    return (
      <section className="page-shell py-16 text-white">
        <div className="glass-panel flex min-h-52 items-center justify-center rounded-3xl" role="status" aria-label={t("common.loading")}>
          <LoaderCircle className="h-7 w-7 animate-spin text-crimson-200" aria-hidden="true" />
        </div>
      </section>
    );
  }

  if (!isAuthenticated) {
    return (
      <section className="page-shell py-10 text-white sm:py-14">
        {header}
        <div className="glass-panel mt-8 flex items-start gap-3 rounded-3xl p-6 sm:p-8">
          <Lock className="mt-0.5 h-5 w-5 shrink-0 text-crimson-200" aria-hidden="true" />
          <div>
            <h2 className="text-lg font-semibold">{t("common.signedOutTitle")}</h2>
            <p className="mt-2 text-sm leading-6 text-white/55">{t("common.signedOutBody")}</p>
            <Link
              href={`/${locale}/login`}
              className="portal-primary-button mt-5 inline-flex h-11 items-center px-5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
            >
              {t("common.login")}
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const weekdayLabels = days.slice(0, 7).map((day) => format.dateTime(day, { weekday: "short" }));

  return (
    <section className="page-shell py-10 text-white sm:py-14">
      {header}
      {error && (
        <StatusMessage tone="error" className="mt-6">
          {error}
        </StatusMessage>
      )}

      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => move(-1)} aria-label={t("calendar.previous")}>
            <ChevronLeft className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setAnchor(startOfDay(new Date()))}>
            {t("calendar.today")}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => move(1)} aria-label={t("calendar.next")}>
            <ChevronRight className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
          </Button>
          <h2 className="ms-2 text-base font-semibold" aria-live="polite">
            {title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-xl border border-white/[0.1] p-1" role="tablist" aria-label={t("calendar.view")}>
            {(["month", "week"] as View[]).map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={view === item}
                onClick={() => setView(item)}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 ${
                  view === item ? "bg-crimson-500/20 text-white" : "text-white/60 hover:text-white"
                }`}
              >
                {t(`calendar.${item}`)}
              </button>
            ))}
          </div>
          <Button size="sm" variant="ghost" disabled={loading} onClick={() => void load()} aria-label={t("calendar.refresh")}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
          </Button>
        </div>
      </div>

      <div className="glass-panel mt-4 overflow-x-auto rounded-3xl p-3 sm:p-4">
        <div className="grid min-w-[44rem] grid-cols-7 gap-2" role="grid" aria-label={title}>
          {weekdayLabels.map((label, index) => (
            <div key={`${label}-${index}`} role="columnheader" className="px-2 pb-1 text-center text-xs font-semibold text-white/45">
              {label}
            </div>
          ))}
          {days.map((day) => {
            const key = dayKey(day);
            const posts = byDay.get(key) || [];
            const outside = view === "month" && day.getMonth() !== anchor.getMonth();
            return (
              <div
                key={key}
                role="gridcell"
                className={`flex flex-col gap-1 rounded-2xl border p-2 ${view === "week" ? "min-h-64" : "min-h-28"} ${
                  key === today ? "border-crimson-500/50 bg-crimson-500/[0.05]" : "border-white/[0.06] bg-black/20"
                } ${outside ? "opacity-45" : ""}`}
              >
                <span className="text-xs font-semibold text-white/60">{format.dateTime(day, { day: "numeric" })}</span>
                {posts.map((post) => {
                  const when = postDate(post);
                  return (
                    <button
                      key={post.id}
                      type="button"
                      onClick={() => void openDetail(post.id)}
                      className={`rounded-xl border px-2 py-1 text-start text-[11px] leading-4 transition hover:brightness-125 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 ${POST_STATUS_TONE[post.status]}`}
                    >
                      <span className="block font-semibold">
                        {when ? format.dateTime(when, { hour: "numeric", minute: "2-digit" }) : ""} · {t(`types.${post.post_type}`)}
                      </span>
                      <span className="block truncate">{post.caption || t("calendar.noCaption")}</span>
                      <span className="mt-1 flex flex-wrap gap-1">
                        {post.targets.map((target) => (
                          <span
                            key={target.id}
                            title={`${target.account_name}: ${t(`targetStatuses.${target.status}`)}`}
                            className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 ${TARGET_STATUS_TONE[target.status]}`}
                          >
                            <PlatformGlyph provider={target.provider} className="h-3 w-3" />
                            <span className="sr-only">
                              {target.account_name}: {t(`targetStatuses.${target.status}`)}
                            </span>
                          </span>
                        ))}
                      </span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>

      {/* Post detail with per-target results */}
      {detail && (
        <div className="glass-panel mt-6 rounded-3xl p-5 sm:p-6" aria-labelledby="calendar-detail-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="calendar-detail-title" className="flex items-center gap-2 text-base font-semibold">
                {t(`types.${detail.post_type}`)}
                <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${POST_STATUS_TONE[detail.status]}`}>
                  {t(`statuses.${detail.status}`)}
                </span>
              </h2>
              <p className="mt-1 text-xs text-white/45">
                {detail.scheduled_at
                  ? t("calendar.when", {
                      date: format.dateTime(new Date(detail.scheduled_at), { dateStyle: "medium", timeStyle: "short" }),
                      timezone: detail.timezone,
                    })
                  : t("calendar.unscheduled")}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {(detail.status === "draft" || detail.status === "scheduled") && (
                <Link
                  href={`/${locale}/social/compose?post=${encodeURIComponent(detail.id)}`}
                  className="portal-secondary-button inline-flex h-9 items-center gap-2 px-3 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
                >
                  <SquarePen className="h-4 w-4" aria-hidden="true" />
                  {t("calendar.edit")}
                </Link>
              )}
              {(detail.status === "scheduled" || detail.status === "publishing") && (
                <Button size="sm" variant="danger" disabled={busy !== null} onClick={() => void cancel(detail)}>
                  {busy === `cancel:${detail.id}` ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <CircleX className="h-4 w-4" aria-hidden="true" />}
                  {t("calendar.cancel")}
                </Button>
              )}
              {(detail.status === "draft" || detail.status === "canceled") && (
                <Button size="sm" variant="danger" disabled={busy !== null} onClick={() => void remove(detail)}>
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  {t("calendar.delete")}
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => void openDetail(detail.id)} disabled={busy !== null}>
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                {t("calendar.refresh")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDetail(null)}>
                {t("calendar.close")}
              </Button>
            </div>
          </div>
          <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-6 text-white/80">{detail.caption || t("calendar.noCaption")}</p>
          <ul className="mt-5 grid gap-3">
            {detail.targets.map((target) => {
              const link = safePermalink(target.permalink);
              const key = issueKey(target.error_code);
              return (
                <li key={target.id} className="rounded-2xl border border-white/[0.08] bg-black/20 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="flex items-center gap-2 text-sm font-semibold">
                      <PlatformGlyph provider={target.provider} />
                      {target.account_name}
                    </span>
                    <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TARGET_STATUS_TONE[target.status]}`}>
                      {t(`targetStatuses.${target.status}`)}
                    </span>
                  </div>
                  {link && (
                    <a
                      href={link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-2 inline-flex items-center gap-1 text-xs text-crimson-200 underline-offset-4 hover:underline"
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      {t("calendar.viewLive")}
                    </a>
                  )}
                  {target.status === "published" && !link && target.remote_post_id && (
                    <p className="mt-2 text-xs text-white/45">{t("calendar.postId", { id: target.remote_post_id })}</p>
                  )}
                  {target.error_code && target.status !== "published" && (
                    <p className="mt-2 text-xs text-rose-100">
                      {key ? t(`issues.${key}`) : t("issues.unknown", { code: target.error_code })}
                      {target.error_message ? ` — ${target.error_message}` : ""}
                    </p>
                  )}
                  {target.status === "retry_wait" && target.next_attempt_at && (
                    <p className="mt-1 text-xs text-amber-100">
                      {t("calendar.retryAt", {
                        date: format.dateTime(new Date(target.next_attempt_at), { timeStyle: "short" }),
                        attempt: target.attempts,
                        max: target.max_attempts,
                      })}
                    </p>
                  )}
                  {target.error_code === "account-reconnect-required" && (
                    <Link href={`/${locale}/social`} className="mt-2 inline-block text-xs text-crimson-200 underline-offset-4 hover:underline">
                      {t("calendar.reconnect")}
                    </Link>
                  )}
                  {target.attempt_log && target.attempt_log.length > 0 && (
                    <details className="mt-2 text-xs text-white/50">
                      <summary className="cursor-pointer">{t("calendar.attempts", { count: target.attempt_log.length })}</summary>
                      <ol className="mt-2 grid gap-1">
                        {target.attempt_log.map((attempt) => (
                          <li key={attempt.attempt_number}>
                            #{attempt.attempt_number} · {attempt.outcome}
                            {attempt.error_code ? ` · ${attempt.error_code}` : ""}
                          </li>
                        ))}
                      </ol>
                    </details>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Drafts have no date, so they are listed under the calendar */}
      <h2 className="mt-10 text-lg font-semibold">{t("calendar.drafts")}</h2>
      {drafts.length === 0 ? (
        <div className="glass-panel mt-4 rounded-3xl p-6 text-sm text-white/50">{t("calendar.noDrafts")}</div>
      ) : (
        <ul className="mt-4 grid gap-2">
          {drafts.map((post) => (
            <li key={post.id} className="glass-panel flex flex-wrap items-center justify-between gap-3 rounded-2xl p-4">
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{t(`types.${post.post_type}`)}</span>
                <span className="block truncate text-xs text-white/50">{post.caption || t("calendar.noCaption")}</span>
              </span>
              <span className="flex gap-2">
                <Link
                  href={`/${locale}/social/compose?post=${encodeURIComponent(post.id)}`}
                  className="portal-secondary-button inline-flex h-9 items-center gap-2 px-3 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
                >
                  {t("calendar.edit")}
                </Link>
                <Button size="sm" variant="ghost" onClick={() => void openDetail(post.id)} disabled={busy !== null}>
                  {t("calendar.details")}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
