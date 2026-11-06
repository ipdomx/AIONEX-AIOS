"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  AlertTriangle,
  Eye,
  EyeOff,
  Inbox,
  LoaderCircle,
  Lock,
  Mail,
  MailOpen,
  MessageCircle,
  MessagesSquare,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  ApiError,
  getSocialInboxConversation,
  getSocialInboxStatus,
  listSocialInboxConversations,
  replySocialInboxConversation,
  setSocialInboxMessageVisibility,
  subscribeSocialInboxAccount,
  suggestSocialInboxReply,
  updateSocialInboxConversation,
} from "@/lib/api";
import type {
  SocialInboxConversation,
  SocialInboxReadiness,
  SocialInboxStatus,
  SocialInboxThread,
} from "@/types";

import { PlatformGlyph } from "./social-publishing-shared";

const REPLY_MAX = 2000;
type PlatformFilter = "all" | "facebook" | "instagram";
type StatusFilter = "all" | SocialInboxStatus;
const STATUSES: SocialInboxStatus[] = ["open", "pending", "closed"];
const STATUS_TONE: Record<SocialInboxStatus, string> = {
  open: "border-sky-400/25 bg-sky-500/10 text-sky-100",
  pending: "border-amber-400/25 bg-amber-500/10 text-amber-100",
  closed: "border-white/[0.12] bg-white/[0.03] text-white/50",
};

/** Maps an API failure to a key under socialInbox.errors. */
function errorKey(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.code === "DAILY_MESSAGE_LIMIT" || cause.code === "MESSAGE_CREDITS_EXHAUSTED") return "aiQuota";
    if (cause.status === 429) return "rateLimited";
    if (cause.code === "messaging-window-closed") return "windowClosed";
    if (cause.code === "account-reconnect-required") return "reconnect";
    if (cause.code === "account-disconnected") return "disconnected";
    if (cause.code === "meta-permission-required") return "permission";
    if (cause.code === "provider-not-configured") return "notConfigured";
    if (cause.code === "reply-outcome-unknown") return "outcomeUnknown";
    if (cause.code === "ai-nothing-to-answer") return "aiNothing";
    if (cause.code === "ai-assistant-unavailable") return "aiUnavailable";
    if (cause.code && cause.code.startsWith("ai-")) return "aiFailed";
    if (cause.status === 404) return "notFound";
  }
  return "generic";
}

export function SocialInboxClient() {
  const t = useTranslations("socialInbox");
  const format = useFormatter();
  const locale = useLocale();
  const { isAuthenticated, isLoading } = useAuth();

  const [readiness, setReadiness] = useState<SocialInboxReadiness | null>(null);
  const [items, setItems] = useState<SocialInboxConversation[]>([]);
  const [unreadTotal, setUnreadTotal] = useState(0);
  const [platform, setPlatform] = useState<PlatformFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [thread, setThread] = useState<SocialInboxThread | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const errorText = useCallback((cause: unknown) => t(`errors.${errorKey(cause)}`), [t]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [status, list] = await Promise.all([
        getSocialInboxStatus(),
        listSocialInboxConversations({
          platform: platform === "all" ? undefined : platform,
          status: statusFilter === "all" ? undefined : statusFilter,
          unread: unreadOnly ? true : undefined,
        }),
      ]);
      setReadiness(status);
      setItems(list.items);
      setUnreadTotal(list.unread_conversations);
      setError("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setLoading(false);
    }
  }, [platform, statusFilter, unreadOnly, errorText]);

  useEffect(() => {
    if (isAuthenticated) void load();
  }, [isAuthenticated, load]);

  function replaceItem(updated: SocialInboxConversation) {
    setItems((current) => current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)));
  }

  async function openConversation(conversation: SocialInboxConversation) {
    setBusy(`open:${conversation.id}`);
    setNotice("");
    try {
      let detail = await getSocialInboxConversation(conversation.id);
      if (detail.unread_count > 0) {
        detail = await updateSocialInboxConversation(conversation.id, { read: true });
        setUnreadTotal((value) => Math.max(0, value - 1));
      }
      setThread(detail);
      replaceItem(detail);
      setDraft("");
      setError("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  async function changeConversation(changes: { read?: boolean; status?: SocialInboxStatus }) {
    if (!thread) return;
    setBusy("update");
    try {
      const detail = await updateSocialInboxConversation(thread.id, changes);
      setThread(detail);
      replaceItem(detail);
      if (changes.read === false) setUnreadTotal((value) => value + 1);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  async function send() {
    if (!thread || !draft.trim()) return;
    setBusy("send");
    setNotice("");
    try {
      const detail = await replySocialInboxConversation(thread.id, draft.trim());
      setThread(detail);
      replaceItem(detail);
      setDraft("");
      setNotice(t("reply.sent"));
      setError("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  async function suggest() {
    if (!thread) return;
    setBusy("suggest");
    try {
      const suggestion = await suggestSocialInboxReply(thread.id, { language: locale, tone: "friendly" });
      setDraft(suggestion.reply.slice(0, REPLY_MAX));
      setNotice(t("reply.suggestionNote"));
      setError("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  async function toggleHidden(messageId: string, hidden: boolean) {
    setBusy(`hide:${messageId}`);
    try {
      const detail = await setSocialInboxMessageVisibility(messageId, hidden);
      setThread(detail);
      setError("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  async function subscribe(accountId: string) {
    setBusy(`subscribe:${accountId}`);
    try {
      await subscribeSocialInboxAccount(accountId);
      setReadiness(await getSocialInboxStatus());
      setNotice(t("readiness.subscribed"));
      setError("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }

  const awaitingMeta = useMemo(() => {
    if (!readiness) return false;
    return (
      !readiness.meta_app_configured ||
      !readiness.webhook_configured ||
      readiness.accounts.length === 0 ||
      readiness.accounts.some((account) => account.state !== "ready")
    );
  }, [readiness]);

  const header = (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-3xl">
        <span className="eyebrow">
          <Inbox className="h-3.5 w-3.5" aria-hidden="true" /> {t("eyebrow")}
        </span>
        <h1 className="section-title mt-6">{t("title")}</h1>
        <p className="section-copy mt-4">{t("description")}</p>
      </div>
      <Link
        href={`/${locale}/social`}
        className="portal-secondary-button inline-flex h-11 items-center gap-2 px-5 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
      >
        <ShieldCheck className="h-4 w-4" aria-hidden="true" />
        {t("accountsLink")}
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

  const replyWindow = thread?.reply_window;
  const windowClosed = Boolean(replyWindow && replyWindow.applies && !replyWindow.open);
  const canReply = Boolean(thread) && !windowClosed && thread?.account_status !== "revoked";

  return (
    <section className="page-shell py-10 text-white sm:py-14">
      {header}
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

      {/* Honest readiness: Meta permissions, App Review and webhook configuration */}
      {readiness && awaitingMeta && (
        <div className="glass-panel mt-8 rounded-3xl border border-amber-400/20 p-5 sm:p-6" aria-labelledby="inbox-readiness-title">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-200" aria-hidden="true" />
            <div className="min-w-0">
              <h2 id="inbox-readiness-title" className="text-base font-semibold">
                {t("readiness.awaitingTitle")}
              </h2>
              <p className="mt-2 text-sm leading-6 text-white/60">{t("readiness.awaitingBody")}</p>
              <ul className="mt-3 grid gap-1 text-sm text-white/60">
                {!readiness.meta_app_configured && <li>{t("readiness.notConfigured")}</li>}
                {!readiness.webhook_configured && <li>{t("readiness.webhookMissing")}</li>}
                {readiness.accounts.length === 0 && (
                  <li>
                    {t("readiness.noAccounts")}{" "}
                    <Link href={`/${locale}/social`} className="text-crimson-200 underline-offset-4 hover:underline">
                      {t("readiness.connectLink")}
                    </Link>
                  </li>
                )}
              </ul>
            </div>
          </div>
        </div>
      )}
      {readiness && readiness.accounts.length > 0 && (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {readiness.accounts.map((account) => (
            <li key={account.account_id} className="glass-panel rounded-2xl p-4 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2 font-semibold">
                  <PlatformGlyph provider={account.provider} />
                  <span className="truncate">{account.display_name}</span>
                </span>
                <span className="rounded-full border border-white/[0.12] px-2.5 py-0.5 text-xs text-white/70">
                  {t(`readiness.states.${account.state}`)}
                </span>
              </div>
              {account.missing_scopes.length > 0 && (
                <p className="mt-2 break-words text-xs text-amber-100">
                  {t("readiness.missingScopes", { scopes: account.missing_scopes.join(", ") })}
                </p>
              )}
              {account.state === "ready" && (
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-white/50">
                  {account.webhook_subscribed_at ? (
                    <span>
                      {t("readiness.subscribedAt", {
                        date: format.dateTime(new Date(account.webhook_subscribed_at), { dateStyle: "medium" }),
                      })}
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy !== null}
                      onClick={() => void subscribe(account.account_id)}
                    >
                      {busy === `subscribe:${account.account_id}` && (
                        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                      )}
                      {t("readiness.subscribe")}
                    </Button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {readiness && !readiness.live_verified && (
        <p className="mt-3 text-xs text-white/40">
          {t("readiness.liveNotVerified", { minutes: Math.round(readiness.poll_seconds / 60) })}
        </p>
      )}

      {/* Filters */}
      <div className="mt-8 flex flex-wrap items-center gap-3" role="group" aria-label={t("filters.label")}>
        <div className="inline-flex rounded-xl border border-white/[0.1] p-1" role="tablist" aria-label={t("filters.platform")}>
          {(["all", "facebook", "instagram"] as PlatformFilter[]).map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={platform === item}
              onClick={() => setPlatform(item)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 ${
                platform === item ? "bg-crimson-500/20 text-white" : "text-white/60 hover:text-white"
              }`}
            >
              {item !== "all" && <PlatformGlyph provider={item} className="h-3.5 w-3.5" />}
              {t(`filters.${item}`)}
            </button>
          ))}
        </div>
        <label className="inline-flex items-center gap-2 text-xs text-white/70">
          <span>{t("filters.status")}</span>
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            className="rounded-lg border border-white/[0.1] bg-black/40 px-2 py-1.5 text-xs text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
          >
            <option value="all">{t("filters.anyStatus")}</option>
            {STATUSES.map((item) => (
              <option key={item} value={item}>
                {t(`statuses.${item}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="inline-flex items-center gap-2 text-xs text-white/70">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(event) => setUnreadOnly(event.target.checked)}
            className="h-4 w-4 accent-crimson-500"
          />
          {t("filters.unreadOnly")}
        </label>
        <span className="text-xs text-white/45">{t("list.unread", { count: unreadTotal })}</span>
        <Button size="sm" variant="ghost" disabled={loading} onClick={() => void load()} aria-label={t("common.refresh")}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
        </Button>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        {/* Conversation list */}
        <div className="glass-panel rounded-3xl p-2 sm:p-3">
          {items.length === 0 ? (
            <p className="p-5 text-sm text-white/50">
              {platform !== "all" || statusFilter !== "all" || unreadOnly ? t("list.emptyFiltered") : t("list.empty")}
            </p>
          ) : (
            <ul className="grid gap-1" aria-label={t("list.label")}>
              {items.map((item) => {
                const active = thread?.id === item.id;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => void openConversation(item)}
                      aria-current={active ? "true" : undefined}
                      className={`flex w-full items-start gap-3 rounded-2xl px-3 py-3 text-start transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 ${
                        active ? "bg-crimson-500/[0.12]" : "hover:bg-white/[0.04]"
                      }`}
                    >
                      <span className="mt-0.5 text-white/70">
                        <PlatformGlyph provider={item.provider} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center justify-between gap-2">
                          <span className={`truncate text-sm ${item.unread_count > 0 ? "font-semibold text-white" : "text-white/80"}`}>
                            {item.participant_name || t("common.unknownParticipant")}
                          </span>
                          {item.last_message_at && (
                            <span className="shrink-0 text-[11px] text-white/40">
                              {format.dateTime(new Date(item.last_message_at), { dateStyle: "short", timeStyle: "short" })}
                            </span>
                          )}
                        </span>
                        <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-white/45">
                          {item.channel === "dm" ? (
                            <MessagesSquare className="h-3 w-3" aria-hidden="true" />
                          ) : (
                            <MessageCircle className="h-3 w-3" aria-hidden="true" />
                          )}
                          {t(`channels.${item.channel}`)} · {item.account_name || ""}
                        </span>
                        <span className="mt-1 block truncate text-xs text-white/55">{item.last_message_preview}</span>
                      </span>
                      {item.unread_count > 0 && (
                        <span className="mt-1 rounded-full bg-crimson-500 px-2 py-0.5 text-[10px] font-semibold text-white">
                          {item.unread_count}
                        </span>
                      )}
                      {busy === `open:${item.id}` && <LoaderCircle className="mt-1 h-4 w-4 animate-spin" aria-hidden="true" />}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Thread view and reply box */}
        <div className="glass-panel flex min-h-[28rem] flex-col rounded-3xl p-4 sm:p-6" aria-live="polite">
          {!thread ? (
            <div className="m-auto max-w-sm text-center text-sm text-white/50">
              <Inbox className="mx-auto mb-3 h-8 w-8 text-white/30" aria-hidden="true" />
              {t("thread.select")}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/[0.07] pb-4">
                <div className="min-w-0">
                  <h2 className="flex items-center gap-2 text-base font-semibold">
                    <PlatformGlyph provider={thread.provider} />
                    <span className="truncate">{thread.participant_name || t("common.unknownParticipant")}</span>
                  </h2>
                  <p className="mt-1 text-xs text-white/45">
                    {t(`channels.${thread.channel}`)} · {t("thread.account", { name: thread.account_name || "" })}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <label className="inline-flex items-center gap-2 text-xs text-white/60">
                    <span className="sr-only">{t("thread.statusLabel")}</span>
                    <select
                      value={thread.status}
                      disabled={busy !== null}
                      onChange={(event) => void changeConversation({ status: event.target.value as SocialInboxStatus })}
                      className={`rounded-full border px-2.5 py-1 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 ${STATUS_TONE[thread.status]} bg-black/40`}
                    >
                      {STATUSES.map((item) => (
                        <option key={item} value={item}>
                          {t(`statuses.${item}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void changeConversation({ read: false })}>
                    <Mail className="h-4 w-4" aria-hidden="true" />
                    {t("thread.markUnread")}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void openConversation(thread)} aria-label={t("common.refresh")}>
                    <RefreshCw className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
              </div>

              <ol className="mt-4 flex flex-1 flex-col gap-3 overflow-y-auto">
                {thread.messages.map((message) => {
                  const outbound = message.direction === "outbound";
                  return (
                    <li key={message.id} className={`flex ${outbound ? "justify-end" : "justify-start"}`}>
                      <div
                        className={`max-w-[85%] rounded-2xl border px-4 py-3 text-sm ${
                          outbound
                            ? "border-crimson-500/30 bg-crimson-500/[0.12]"
                            : "border-white/[0.08] bg-black/30"
                        } ${message.hidden ? "opacity-60" : ""}`}
                      >
                        <p className="text-[11px] text-white/45">
                          {outbound ? t("thread.business") : message.author_name || t("common.unknownParticipant")} ·{" "}
                          {format.dateTime(new Date(message.sent_at), { dateStyle: "medium", timeStyle: "short" })}
                        </p>
                        {message.removed ? (
                          <p className="mt-1 italic text-white/45">{t("thread.removed")}</p>
                        ) : (
                          <p className="mt-1 whitespace-pre-wrap break-words leading-6 text-white/85">{message.body}</p>
                        )}
                        {message.attachments.length > 0 && (
                          <p className="mt-1 text-[11px] text-white/45">
                            {message.attachments.map((item) => t("thread.attachment", { type: item.type })).join(" · ")}
                          </p>
                        )}
                        {message.hidden && (
                          <p className="mt-1 inline-flex items-center gap-1 text-[11px] text-amber-100">
                            <EyeOff className="h-3 w-3" aria-hidden="true" />
                            {t("thread.hidden")}
                          </p>
                        )}
                        {thread.channel === "comment" && !outbound && !message.removed && (
                          <div className="mt-2">
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy !== null || thread.account_status === "revoked"}
                              onClick={() => void toggleHidden(message.id, !message.hidden)}
                            >
                              {busy === `hide:${message.id}` ? (
                                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                              ) : message.hidden ? (
                                <Eye className="h-4 w-4" aria-hidden="true" />
                              ) : (
                                <EyeOff className="h-4 w-4" aria-hidden="true" />
                              )}
                              {message.hidden ? t("thread.unhide") : t("thread.hide")}
                            </Button>
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>

              {/* 24-hour messaging window */}
              {replyWindow?.applies && replyWindow.open && replyWindow.expires_at && (
                <p className="mt-4 text-xs text-white/45">
                  {t("thread.windowOpen", {
                    date: format.dateTime(new Date(replyWindow.expires_at), { dateStyle: "medium", timeStyle: "short" }),
                  })}
                </p>
              )}
              {windowClosed && (
                <StatusMessage tone="error" className="mt-4">
                  <span className="font-semibold">{t("thread.windowClosedTitle")}</span> {t("thread.windowClosedBody")}
                </StatusMessage>
              )}

              <form
                className="mt-4 border-t border-white/[0.07] pt-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void send();
                }}
              >
                <label htmlFor="inbox-reply" className="text-xs font-semibold text-white/70">
                  {thread.channel === "dm" ? t("reply.labelDm") : t("reply.labelComment")}
                </label>
                <textarea
                  id="inbox-reply"
                  value={draft}
                  maxLength={REPLY_MAX}
                  disabled={!canReply || busy === "send"}
                  onChange={(event) => setDraft(event.target.value)}
                  rows={3}
                  placeholder={t("reply.placeholder")}
                  className="mt-2 w-full resize-y rounded-2xl border border-white/[0.1] bg-black/40 px-4 py-3 text-sm text-white placeholder:text-white/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 disabled:opacity-50"
                />
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[11px] text-white/40">
                    {t("reply.counter", { count: draft.length, max: REPLY_MAX })}
                  </span>
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" size="sm" variant="secondary" disabled={!canReply || busy !== null} onClick={() => void suggest()}>
                      {busy === "suggest" ? (
                        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                      ) : (
                        <Sparkles className="h-4 w-4" aria-hidden="true" />
                      )}
                      {t("reply.suggest")}
                    </Button>
                    <Button type="submit" size="sm" disabled={!canReply || busy !== null || !draft.trim()}>
                      {busy === "send" ? (
                        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                      ) : (
                        <Send className="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
                      )}
                      {t("reply.send")}
                    </Button>
                  </div>
                </div>
                {thread.unread_count === 0 && (
                  <p className="mt-2 inline-flex items-center gap-1 text-[11px] text-white/35">
                    <MailOpen className="h-3 w-3" aria-hidden="true" />
                    {t("thread.read")}
                  </p>
                )}
              </form>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
