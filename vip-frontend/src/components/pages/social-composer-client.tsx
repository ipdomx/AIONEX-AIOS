"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  CalendarClock,
  CalendarDays,
  Film,
  ImageIcon,
  LoaderCircle,
  Lock,
  Save,
  Send,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  createSocialPost,
  getSocialPost,
  listSocialAccounts,
  listSocialMedia,
  publishSocialPostNow,
  scheduleSocialPost,
  socialAiAssist,
  updateSocialPost,
  uploadSocialMedia,
  validateSocialPost,
} from "@/lib/api";
import type {
  SocialAccount,
  SocialAiAssistResult,
  SocialMediaItem,
  SocialPost,
  SocialPostInput,
  SocialPostType,
  SocialValidationReport,
} from "@/types";

import {
  POST_STATUS_TONE,
  PlatformGlyph,
  apiErrorKey,
  formatBytes,
  issueKey,
} from "./social-publishing-shared";

const POST_TYPES: SocialPostType[] = ["text", "link", "image", "carousel", "video", "reel"];
const IG_CAPTION_MAX = 2200;
const IG_HASHTAGS_MAX = 30;
const IG_PREVIEW_CHARS = 125;
const TONES = ["friendly", "professional", "playful", "inspiring", "promotional"] as const;
const AI_LANGUAGES = ["ar", "en", "fr", "de", "es", "tr"] as const;
const PUBLISHABLE = new Set(["facebook", "instagram"]);
const EDITABLE = new Set(["draft", "scheduled"]);
const POST_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

type Override = { caption?: string; share_to_feed?: boolean };
type Notice = { tone: "success" | "error" | "info"; text: string } | null;

function newKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function hashtagCount(text: string): number {
  return (text.match(/(?:^|[^\w#])#[^\s#.,!?;:]+/g) || []).length;
}

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function toLocalInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function SocialComposerClient() {
  const t = useTranslations("socialPublishing");
  const locale = useLocale();
  const { isAuthenticated, isLoading } = useAuth();

  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [library, setLibrary] = useState<SocialMediaItem[]>([]);
  const [loadError, setLoadError] = useState("");
  const [loaded, setLoaded] = useState(false);

  const [post, setPost] = useState<SocialPost | null>(null);
  const [postType, setPostType] = useState<SocialPostType>("text");
  const [caption, setCaption] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [media, setMedia] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  const [scheduleAt, setScheduleAt] = useState("");
  const [timezone] = useState(browserTimezone);
  const idempotencyKey = useRef(newKey());

  const [report, setReport] = useState<SocialValidationReport | null>(null);
  const [validating, setValidating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const [aiTopic, setAiTopic] = useState("");
  const [aiTone, setAiTone] = useState<(typeof TONES)[number]>("friendly");
  const [aiLanguage, setAiLanguage] = useState<string>(
    (AI_LANGUAGES as readonly string[]).includes(locale) ? locale : "ar",
  );
  const [aiResult, setAiResult] = useState<SocialAiAssistResult | null>(null);

  const errorText = useCallback((cause: unknown) => t(`errors.${apiErrorKey(cause)}`), [t]);

  const loadAll = useCallback(async () => {
    try {
      const [accountList, mediaList] = await Promise.all([listSocialAccounts(), listSocialMedia()]);
      setAccounts(accountList.items.filter((item) => PUBLISHABLE.has(item.provider)));
      setLibrary([...mediaList.uploads, ...mediaList.studio]);
      setLoadError("");
    } catch (cause) {
      setLoadError(errorText(cause));
    } finally {
      setLoaded(true);
    }
  }, [errorText]);

  // Editing: /<locale>/social/compose/?post=<id> loads an editable post once.
  useEffect(() => {
    if (!isAuthenticated) return;
    void loadAll();
    const postId = new URLSearchParams(window.location.search).get("post");
    if (!postId || !POST_ID_RE.test(postId)) return;
    getSocialPost(postId)
      .then((existing) => {
        setPost(existing);
        setPostType(existing.post_type);
        setCaption(existing.caption);
        setLinkUrl(existing.link_url || "");
        setMedia(existing.media.map((item) => item.ref));
        setSelected(new Set(existing.targets.map((item) => item.account_id || "").filter(Boolean)));
        const next: Record<string, Override> = {};
        for (const target of existing.targets) {
          if (target.account_id && Object.keys(target.overrides || {}).length > 0)
            next[target.account_id] = target.overrides;
        }
        setOverrides(next);
        setScheduleAt(toLocalInput(existing.scheduled_at));
      })
      .catch((cause) => setNotice({ tone: "error", text: errorText(cause) }));
  }, [isAuthenticated, loadAll, errorText]);

  const chosenAccounts = useMemo(
    () => accounts.filter((account) => selected.has(account.id)),
    [accounts, selected],
  );
  const libraryByRef = useMemo(() => new Map(library.map((item) => [item.ref, item])), [library]);
  const editable = !post || EDITABLE.has(post.status);

  const input = useMemo<SocialPostInput>(() => {
    const cleaned: Record<string, Override> = {};
    for (const [accountId, value] of Object.entries(overrides)) {
      if (!selected.has(accountId)) continue;
      const entry: Override = {};
      if (value.caption !== undefined && value.caption !== "") entry.caption = value.caption;
      if (value.share_to_feed !== undefined) entry.share_to_feed = value.share_to_feed;
      if (Object.keys(entry).length) cleaned[accountId] = entry;
    }
    return {
      post_type: postType,
      caption,
      link_url: postType === "link" && linkUrl.trim() ? linkUrl.trim() : null,
      media: postType === "text" || postType === "link" ? [] : media,
      account_ids: Array.from(selected),
      overrides: cleaned,
      timezone,
      client_idempotency_key: idempotencyKey.current,
    };
  }, [postType, caption, linkUrl, media, selected, overrides, timezone]);

  // Live, server-authoritative validation (debounced) while the user edits.
  useEffect(() => {
    if (!isAuthenticated || input.account_ids.length === 0) {
      setReport(null);
      return;
    }
    const handle = window.setTimeout(() => {
      setValidating(true);
      validateSocialPost(input)
        .then(setReport)
        .catch(() => setReport(null))
        .finally(() => setValidating(false));
    }, 600);
    return () => window.clearTimeout(handle);
  }, [input, isAuthenticated]);

  const issuesFor = useCallback(
    (accountId: string) => report?.targets.find((item) => item.account_id === accountId)?.issues || [],
    [report],
  );
  const hasErrors = report ? !report.valid : false;

  function toggleAccount(accountId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(accountId)) next.delete(accountId);
      else next.add(accountId);
      return next;
    });
  }

  function toggleMedia(ref: string) {
    setMedia((current) =>
      current.includes(ref) ? current.filter((item) => item !== ref) : current.length >= 10 ? current : [...current, ref],
    );
  }

  async function onUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy("upload");
    setNotice(null);
    try {
      const item = await uploadSocialMedia(file);
      setLibrary((current) => [item, ...current]);
      setMedia((current) => (current.length >= 10 ? current : [...current, item.ref]));
    } catch (cause) {
      setNotice({ tone: "error", text: errorText(cause) });
    } finally {
      setBusy(null);
    }
  }

  async function saveDraft(): Promise<SocialPost | null> {
    try {
      const saved = post ? await updateSocialPost(post.id, input) : await createSocialPost(input);
      setPost(saved);
      return saved;
    } catch (cause) {
      setNotice({ tone: "error", text: errorText(cause) });
      return null;
    }
  }

  async function onSave() {
    setBusy("save");
    setNotice(null);
    const saved = await saveDraft();
    if (saved) setNotice({ tone: "success", text: t("composer.saved") });
    setBusy(null);
  }

  async function onPublishNow() {
    setBusy("publish");
    setNotice(null);
    const saved = await saveDraft();
    if (saved) {
      try {
        const queued = await publishSocialPostNow(saved.id);
        setPost(queued);
        setNotice({ tone: "info", text: t("composer.queued") });
      } catch (cause) {
        setNotice({ tone: "error", text: errorText(cause) });
      }
    }
    setBusy(null);
  }

  async function onSchedule() {
    const date = new Date(scheduleAt);
    if (!scheduleAt || Number.isNaN(date.getTime())) {
      setNotice({ tone: "error", text: t("errors.scheduleMissing") });
      return;
    }
    setBusy("schedule");
    setNotice(null);
    const saved = await saveDraft();
    if (saved) {
      try {
        const scheduled = await scheduleSocialPost(saved.id, date.toISOString(), timezone);
        setPost(scheduled);
        setNotice({ tone: "success", text: t("composer.scheduled") });
      } catch (cause) {
        setNotice({ tone: "error", text: errorText(cause) });
      }
    }
    setBusy(null);
  }

  async function runAssist(mode: "draft" | "improve" | "hashtags") {
    setBusy(`ai:${mode}`);
    setNotice(null);
    setAiResult(null);
    try {
      const platforms = Array.from(new Set(chosenAccounts.map((item) => item.provider))).filter(
        (item): item is "facebook" | "instagram" => item === "facebook" || item === "instagram",
      );
      const result = await socialAiAssist({
        mode,
        text: caption,
        topic: aiTopic,
        language: aiLanguage,
        platforms,
        tone: aiTone,
      });
      setAiResult(result);
    } catch (cause) {
      setNotice({ tone: "error", text: errorText(cause) });
    } finally {
      setBusy(null);
    }
  }

  function applyAi(withHashtags: boolean) {
    if (!aiResult) return;
    const base = aiResult.mode === "hashtags" ? caption : aiResult.caption;
    const tags = withHashtags && aiResult.hashtags.length ? `\n\n${aiResult.hashtags.join(" ")}` : "";
    setCaption(`${base}${tags}`.slice(0, 63206));
    setAiResult(null);
  }

  function issueText(code: string): string {
    const key = issueKey(code);
    return key ? t(`issues.${key}`) : t("issues.unknown", { code });
  }

  const header = (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-3xl">
        <span className="eyebrow">
          <Send className="h-3.5 w-3.5" aria-hidden="true" /> {t("composer.eyebrow")}
        </span>
        <h1 className="section-title mt-6">{t("composer.title")}</h1>
        <p className="section-copy mt-4">{t("composer.description")}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Link
          href={`/${locale}/social/calendar`}
          className="portal-secondary-button inline-flex h-11 items-center gap-2 px-5 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
        >
          <CalendarDays className="h-4 w-4" aria-hidden="true" />
          {t("nav.calendar")}
        </Link>
        <Link
          href={`/${locale}/social`}
          className="portal-secondary-button inline-flex h-11 items-center gap-2 px-5 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
        >
          {t("nav.accounts")}
        </Link>
      </div>
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

  const needsMedia = postType !== "text" && postType !== "link";
  const instagramChosen = chosenAccounts.some((item) => item.provider === "instagram");
  const igOver = caption.length > IG_CAPTION_MAX;
  const tags = hashtagCount(caption);
  const selectedMedia = media.map((ref) => libraryByRef.get(ref) || null);

  return (
    <section className="page-shell py-10 text-white sm:py-14">
      {header}

      {notice && (
        <StatusMessage tone={notice.tone} className="mt-6">
          {notice.text}
        </StatusMessage>
      )}
      {loadError && (
        <StatusMessage tone="error" className="mt-4">
          {loadError}
        </StatusMessage>
      )}
      <StatusMessage className="mt-6">{t("composer.honesty")}</StatusMessage>
      {post && (
        <p className="mt-4 text-sm text-white/60">
          {t("composer.currentStatus")}{" "}
          <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${POST_STATUS_TONE[post.status]}`}>
            {t(`statuses.${post.status}`)}
          </span>{" "}
          {!editable && (
            <Link href={`/${locale}/social/calendar`} className="text-crimson-200 underline-offset-4 hover:underline">
              {t("composer.viewResults")}
            </Link>
          )}
        </p>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="grid gap-6">
          {/* Accounts */}
          <fieldset className="glass-panel rounded-3xl p-5 sm:p-6" disabled={!editable}>
            <legend className="px-1 text-base font-semibold">{t("composer.accounts")}</legend>
            {loaded && accounts.length === 0 ? (
              <p className="mt-3 text-sm text-white/55">
                {t("composer.noAccounts")}{" "}
                <Link href={`/${locale}/social`} className="text-crimson-200 underline-offset-4 hover:underline">
                  {t("nav.accounts")}
                </Link>
              </p>
            ) : (
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {accounts.map((account) => {
                  const id = `compose-account-${account.id}`;
                  const reconnect = account.status !== "active";
                  return (
                    <li key={account.id}>
                      <label
                        htmlFor={id}
                        className="flex cursor-pointer items-center gap-3 rounded-2xl border border-white/[0.08] bg-black/20 p-3 transition hover:border-white/20 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"
                      >
                        <input
                          id={id}
                          type="checkbox"
                          className="h-4 w-4 accent-crimson-500"
                          checked={selected.has(account.id)}
                          disabled={reconnect}
                          onChange={() => toggleAccount(account.id)}
                        />
                        <PlatformGlyph provider={account.provider} />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold">{account.display_name}</span>
                          <span className="block truncate text-xs text-white/45">
                            {reconnect ? t("composer.reconnect") : account.handle ? `@${account.handle}` : t(`platforms.${account.provider}`)}
                          </span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </fieldset>

          {/* Content */}
          <fieldset className="glass-panel grid gap-4 rounded-3xl p-5 sm:p-6" disabled={!editable}>
            <legend className="px-1 text-base font-semibold">{t("composer.content")}</legend>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t("composer.postType")}>
              {POST_TYPES.map((type) => (
                <button
                  key={type}
                  type="button"
                  role="radio"
                  aria-checked={postType === type}
                  onClick={() => setPostType(type)}
                  className={`rounded-xl border px-3 py-2 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 ${
                    postType === type
                      ? "border-crimson-500/60 bg-crimson-500/15 text-white"
                      : "border-white/[0.1] bg-black/20 text-white/65 hover:border-white/25"
                  }`}
                >
                  {t(`types.${type}`)}
                </button>
              ))}
            </div>
            <label className="grid gap-2 text-sm">
              <span className="font-semibold">{t("composer.caption")}</span>
              <textarea
                value={caption}
                maxLength={63206}
                rows={7}
                onChange={(event) => setCaption(event.target.value)}
                className="w-full rounded-xl border border-white/[0.14] bg-obsidian-700 p-4 text-sm leading-6 text-white outline-none transition placeholder:text-zinc-500 focus:border-crimson-500 focus:ring-2 focus:ring-crimson-500"
                placeholder={t("composer.captionPlaceholder")}
              />
              <span className={`text-xs ${igOver && instagramChosen ? "text-rose-200" : "text-white/45"}`}>
                {t("composer.counter", { count: caption.length, max: IG_CAPTION_MAX, tags, maxTags: IG_HASHTAGS_MAX })}
              </span>
            </label>
            {postType === "link" && (
              <label className="grid gap-2 text-sm">
                <span className="font-semibold">{t("composer.link")}</span>
                <Input
                  type="url"
                  inputMode="url"
                  value={linkUrl}
                  placeholder="https://"
                  onChange={(event) => setLinkUrl(event.target.value)}
                />
              </label>
            )}
          </fieldset>

          {/* Media */}
          {needsMedia && (
            <fieldset className="glass-panel rounded-3xl p-5 sm:p-6" disabled={!editable}>
              <legend className="px-1 text-base font-semibold">{t("composer.media")}</legend>
              <p className="mt-1 text-xs leading-5 text-white/50">{t("composer.mediaHint")}</p>
              <label className="portal-secondary-button mt-4 inline-flex h-11 cursor-pointer items-center gap-2 px-5 text-sm font-semibold focus-within:ring-2 focus-within:ring-crimson-500">
                {busy === "upload" ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Upload className="h-4 w-4" aria-hidden="true" />
                )}
                {t("composer.upload")}
                <input
                  type="file"
                  className="sr-only"
                  accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime"
                  onChange={(event) => void onUpload(event)}
                  disabled={busy !== null}
                />
              </label>
              {selectedMedia.length > 0 && (
                <ol className="mt-4 grid gap-2">
                  {selectedMedia.map((item, index) => (
                    <li
                      key={media[index]}
                      className="flex items-center justify-between gap-3 rounded-2xl border border-crimson-500/30 bg-crimson-500/[0.06] p-3 text-sm"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        {item?.kind === "video" ? (
                          <Film className="h-4 w-4 shrink-0" aria-hidden="true" />
                        ) : (
                          <ImageIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                        )}
                        <span className="truncate">
                          {index + 1}. {item ? item.title || item.filename : t("composer.mediaUnknown")}
                        </span>
                        {item && (
                          <span className="shrink-0 text-xs text-white/45">
                            {formatBytes(item.size_bytes)}
                            {item.width && item.height ? ` · ${item.width}×${item.height}` : ""}
                            {item.duration_ms ? ` · ${Math.round(item.duration_ms / 1000)}s` : ""}
                          </span>
                        )}
                      </span>
                      <Button size="sm" variant="ghost" onClick={() => toggleMedia(media[index])} aria-label={t("composer.removeMedia")}>
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </li>
                  ))}
                </ol>
              )}
              <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-white/45">{t("composer.library")}</h3>
              {library.length === 0 ? (
                <p className="mt-2 text-sm text-white/45">{t("composer.libraryEmpty")}</p>
              ) : (
                <ul className="mt-2 grid max-h-72 gap-2 overflow-y-auto pe-1 sm:grid-cols-2">
                  {library.map((item) => (
                    <li key={item.ref}>
                      <button
                        type="button"
                        onClick={() => toggleMedia(item.ref)}
                        aria-pressed={media.includes(item.ref)}
                        className={`flex w-full items-center gap-2 rounded-2xl border p-3 text-start text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 ${
                          media.includes(item.ref)
                            ? "border-crimson-500/50 bg-crimson-500/10"
                            : "border-white/[0.08] bg-black/20 hover:border-white/20"
                        }`}
                      >
                        {item.kind === "video" ? (
                          <Film className="h-4 w-4 shrink-0" aria-hidden="true" />
                        ) : (
                          <ImageIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                        )}
                        <span className="min-w-0">
                          <span className="block truncate">{item.title || item.filename}</span>
                          <span className="block text-xs text-white/45">
                            {t(`sources.${item.source}`)} · {formatBytes(item.size_bytes)}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>
          )}

          {/* Per-account overrides */}
          {chosenAccounts.length > 0 && (
            <fieldset className="glass-panel rounded-3xl p-5 sm:p-6" disabled={!editable}>
              <legend className="px-1 text-base font-semibold">{t("composer.overrides")}</legend>
              <p className="mt-1 text-xs leading-5 text-white/50">{t("composer.overridesHint")}</p>
              <div className="mt-4 grid gap-4">
                {chosenAccounts.map((account) => (
                  <div key={account.id} className="rounded-2xl border border-white/[0.08] bg-black/20 p-3">
                    <p className="flex items-center gap-2 text-sm font-semibold">
                      <PlatformGlyph provider={account.provider} />
                      {account.display_name}
                    </p>
                    <textarea
                      rows={3}
                      value={overrides[account.id]?.caption ?? ""}
                      placeholder={t("composer.overridePlaceholder")}
                      aria-label={t("composer.overrideFor", { name: account.display_name })}
                      onChange={(event) =>
                        setOverrides((current) => ({
                          ...current,
                          [account.id]: { ...current[account.id], caption: event.target.value },
                        }))
                      }
                      className="mt-2 w-full rounded-xl border border-white/[0.14] bg-obsidian-700 p-3 text-sm text-white outline-none focus:border-crimson-500 focus:ring-2 focus:ring-crimson-500"
                    />
                    {account.provider === "instagram" && postType === "reel" && (
                      <label className="mt-2 flex items-center gap-2 text-xs text-white/70">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-crimson-500"
                          checked={overrides[account.id]?.share_to_feed ?? true}
                          onChange={(event) =>
                            setOverrides((current) => ({
                              ...current,
                              [account.id]: { ...current[account.id], share_to_feed: event.target.checked },
                            }))
                          }
                        />
                        {t("composer.shareToFeed")}
                      </label>
                    )}
                  </div>
                ))}
              </div>
            </fieldset>
          )}
        </div>

        <div className="grid content-start gap-6">
          {/* AI assist */}
          <section className="glass-panel rounded-3xl p-5 sm:p-6" aria-labelledby="compose-ai-title">
            <h2 id="compose-ai-title" className="flex items-center gap-2 text-base font-semibold">
              <Sparkles className="h-4 w-4 text-crimson-200" aria-hidden="true" />
              {t("ai.title")}
            </h2>
            <p className="mt-1 text-xs leading-5 text-white/50">{t("ai.body")}</p>
            <div className="mt-4 grid gap-3">
              <Input value={aiTopic} maxLength={1000} placeholder={t("ai.topicPlaceholder")} onChange={(event) => setAiTopic(event.target.value)} aria-label={t("ai.topic")} />
              <div className="grid grid-cols-2 gap-2">
                <label className="grid gap-1 text-xs text-white/60">
                  {t("ai.tone")}
                  <select
                    value={aiTone}
                    onChange={(event) => setAiTone(event.target.value as (typeof TONES)[number])}
                    className="h-10 rounded-xl border border-white/[0.14] bg-obsidian-700 px-3 text-sm text-white"
                  >
                    {TONES.map((tone) => (
                      <option key={tone} value={tone}>
                        {t(`ai.tones.${tone}`)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-xs text-white/60">
                  {t("ai.language")}
                  <select
                    value={aiLanguage}
                    onChange={(event) => setAiLanguage(event.target.value)}
                    className="h-10 rounded-xl border border-white/[0.14] bg-obsidian-700 px-3 text-sm text-white"
                  >
                    {AI_LANGUAGES.map((code) => (
                      <option key={code} value={code}>
                        {t(`ai.languages.${code}`)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={busy !== null || !aiTopic.trim() || !editable} onClick={() => void runAssist("draft")}>
                  {busy === "ai:draft" ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Sparkles className="h-4 w-4" aria-hidden="true" />}
                  {t("ai.draft")}
                </Button>
                <Button size="sm" variant="secondary" disabled={busy !== null || !caption.trim() || !editable} onClick={() => void runAssist("improve")}>
                  {busy === "ai:improve" && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />}
                  {t("ai.improve")}
                </Button>
                <Button size="sm" variant="secondary" disabled={busy !== null || !caption.trim() || !editable} onClick={() => void runAssist("hashtags")}>
                  {busy === "ai:hashtags" && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />}
                  {t("ai.hashtags")}
                </Button>
              </div>
              {aiResult && (
                <div className="rounded-2xl border border-white/[0.1] bg-black/25 p-3 text-sm">
                  <p className="text-xs text-white/45">{t("ai.byModel", { model: aiResult.aionex_ai ? "AIONEX AI" : aiResult.model })}</p>
                  {aiResult.mode !== "hashtags" && <p className="mt-2 whitespace-pre-wrap leading-6">{aiResult.caption}</p>}
                  {aiResult.hashtags.length > 0 && <p className="mt-2 text-crimson-100">{aiResult.hashtags.join(" ")}</p>}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {aiResult.mode !== "hashtags" && (
                      <Button size="sm" onClick={() => applyAi(false)}>
                        {t("ai.useCaption")}
                      </Button>
                    )}
                    {aiResult.hashtags.length > 0 && (
                      <Button size="sm" variant="secondary" onClick={() => applyAi(true)}>
                        {aiResult.mode === "hashtags" ? t("ai.addHashtags") : t("ai.useBoth")}
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => setAiResult(null)}>
                      {t("ai.discard")}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Previews and validation per account */}
          <section className="glass-panel rounded-3xl p-5 sm:p-6" aria-labelledby="compose-preview-title">
            <h2 id="compose-preview-title" className="flex items-center gap-2 text-base font-semibold">
              {t("composer.preview")}
              {validating && <LoaderCircle className="h-4 w-4 animate-spin text-white/50" aria-label={t("composer.validating")} />}
            </h2>
            {chosenAccounts.length === 0 ? (
              <p className="mt-3 text-sm text-white/45">{t("composer.previewEmpty")}</p>
            ) : (
              <ul className="mt-4 grid gap-4">
                {chosenAccounts.map((account) => {
                  const own = overrides[account.id]?.caption;
                  const text = own && own.length ? own : caption;
                  const shown =
                    account.provider === "instagram" && text.length > IG_PREVIEW_CHARS
                      ? `${text.slice(0, IG_PREVIEW_CHARS)}… ${t("composer.more")}`
                      : text;
                  const issues = issuesFor(account.id);
                  return (
                    <li key={account.id} className="rounded-2xl border border-white/[0.1] bg-obsidian-900/60 p-4">
                      <p className="flex items-center gap-2 text-sm font-semibold">
                        <PlatformGlyph provider={account.provider} />
                        {account.display_name}
                        <span className="text-xs font-normal text-white/40">{t(`platforms.${account.provider}`)}</span>
                      </p>
                      {needsMedia && (
                        <p className="mt-3 rounded-xl border border-dashed border-white/[0.14] px-3 py-6 text-center text-xs text-white/45">
                          {t("composer.previewMedia", { count: media.length, type: t(`types.${postType}`) })}
                        </p>
                      )}
                      <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-white/85">{shown || t("composer.previewNoText")}</p>
                      {postType === "link" && linkUrl && <p className="mt-2 truncate text-xs text-sky-200">{linkUrl}</p>}
                      {issues.length > 0 && (
                        <ul className="mt-3 grid gap-1">
                          {issues.map((item) => (
                            <li
                              key={`${item.code}-${item.field}`}
                              className={`rounded-lg px-2 py-1 text-xs ${
                                item.severity === "error" ? "bg-rose-500/10 text-rose-100" : "bg-amber-500/10 text-amber-100"
                              }`}
                            >
                              {item.severity === "error" ? t("composer.blocking") : t("composer.warning")}: {issueText(item.code)}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Actions */}
          <section className="glass-panel grid gap-3 rounded-3xl p-5 sm:p-6" aria-labelledby="compose-actions-title">
            <h2 id="compose-actions-title" className="text-base font-semibold">
              {t("composer.when")}
            </h2>
            <label className="grid gap-1 text-xs text-white/60">
              {t("composer.scheduleAt", { timezone })}
              <Input type="datetime-local" value={scheduleAt} onChange={(event) => setScheduleAt(event.target.value)} disabled={!editable} />
            </label>
            {hasErrors && <StatusMessage tone="error">{t("composer.fixErrors")}</StatusMessage>}
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" disabled={busy !== null || !editable || selected.size === 0} onClick={() => void onSave()}>
                {busy === "save" ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}
                {t("composer.saveDraft")}
              </Button>
              <Button variant="secondary" disabled={busy !== null || !editable || selected.size === 0 || hasErrors || !scheduleAt} onClick={() => void onSchedule()}>
                {busy === "schedule" ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <CalendarClock className="h-4 w-4" aria-hidden="true" />}
                {t("composer.schedule")}
              </Button>
              <Button disabled={busy !== null || !editable || selected.size === 0 || hasErrors} onClick={() => void onPublishNow()}>
                {busy === "publish" ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
                {t("composer.publishNow", { count: selected.size })}
              </Button>
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}
