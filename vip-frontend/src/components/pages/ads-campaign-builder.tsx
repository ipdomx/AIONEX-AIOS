"use client";

import { LoaderCircle, Pause, Play, RotateCcw, Send, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import {
  activateAdsCampaign,
  createAdsCampaign,
  listAdsCampaigns,
  listSocialAccounts,
  listSocialMedia,
  listSocialPosts,
  pauseAdsCampaign,
  provisionAdsCampaign,
} from "@/lib/api";
import type {
  AdAccountLink,
  AdsAccess,
  AdsCampaign,
  AdsCampaignInput,
  AdsObjective,
  SocialAccount,
  SocialMediaItem,
  SocialPostTarget,
} from "@/types";

import { adsErrorText, currencyOffset, moneyMinor, money, toMinor } from "./ads-shared";

const OBJECTIVES: AdsObjective[] = ["traffic", "awareness", "engagement"];
const CTAS = ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "CONTACT_US", "BOOK_TRAVEL", "DOWNLOAD", "GET_OFFER"];
const STATUSES = ["draft", "provisioning", "paused", "active", "auto_paused", "failed"];

function newKey(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

export function AdsCampaignBuilder({ access, links }: { access: AdsAccess; links: AdAccountLink[] }) {
  const t = useTranslations("ads");
  const [campaigns, setCampaigns] = useState<AdsCampaign[]>([]);
  const [pages, setPages] = useState<SocialAccount[]>([]);
  const [media, setMedia] = useState<SocialMediaItem[]>([]);
  const [posts, setPosts] = useState<SocialPostTarget[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);

  const [linkId, setLinkId] = useState(links[0]?.id ?? "");
  const [name, setName] = useState("");
  const [objective, setObjective] = useState<AdsObjective>("traffic");
  const [budgetType, setBudgetType] = useState<"daily" | "lifetime">("daily");
  const [budget, setBudget] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [countries, setCountries] = useState("");
  const [ageMin, setAgeMin] = useState("18");
  const [ageMax, setAgeMax] = useState("65");
  const [gender, setGender] = useState<"all" | "1" | "2">("all");
  const [platforms, setPlatforms] = useState<Set<"facebook" | "instagram">>(new Set(["facebook", "instagram"]));
  const [source, setSource] = useState<"post" | "upload">("post");
  const [postTargetId, setPostTargetId] = useState("");
  const [mediaRef, setMediaRef] = useState("");
  const [pageId, setPageId] = useState("");
  const [instagramId, setInstagramId] = useState("");
  const [text, setText] = useState("");
  const [headline, setHeadline] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [cta, setCta] = useState("LEARN_MORE");

  const [activating, setActivating] = useState<AdsCampaign | null>(null);
  const [phrase, setPhrase] = useState("");
  const [confirmBudget, setConfirmBudget] = useState("");

  const link = links.find((item) => item.id === linkId) ?? links[0] ?? null;
  const currency = link?.currency ?? "USD";

  const load = useCallback(async () => {
    try {
      const [campaignList, accounts, library, postList] = await Promise.all([
        listAdsCampaigns(),
        listSocialAccounts(),
        listSocialMedia(),
        listSocialPosts(),
      ]);
      setCampaigns(campaignList.items);
      setPages(accounts.items.filter((item) => item.status === "active"));
      setMedia([...library.uploads, ...library.studio].filter((item) => item.kind === "image"));
      setPosts(
        postList.items.flatMap((post) =>
          post.targets.filter((target) => target.status === "published" && target.remote_post_id),
        ),
      );
    } catch (cause) {
      setError(adsErrorText(t, cause));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const facebookPages = useMemo(() => pages.filter((item) => item.provider === "facebook"), [pages]);
  const instagramAccounts = useMemo(() => pages.filter((item) => item.provider === "instagram"), [pages]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    const amount = toMinor(budget, currency);
    const countryList = countries
      .split(",")
      .map((item) => item.trim().toUpperCase())
      .filter((item) => /^[A-Z]{2}$/.test(item));
    const creativeReady = source === "post" ? Boolean(postTargetId) : Boolean(mediaRef && pageId && text.trim() && linkUrl.startsWith("https://"));
    if (!link || !name.trim() || !amount || !countryList.length || !platforms.size || !creativeReady || (budgetType === "lifetime" && !end)) {
      setError(t("create.invalid"));
      return;
    }
    const input: AdsCampaignInput = {
      link_id: link.id,
      name: name.trim(),
      objective,
      daily_budget_minor: budgetType === "daily" ? amount : null,
      lifetime_budget_minor: budgetType === "lifetime" ? amount : null,
      start_time: start ? new Date(start).toISOString() : null,
      end_time: end ? new Date(end).toISOString() : null,
      targeting: {
        countries: countryList,
        age_min: Number(ageMin) || 18,
        age_max: Number(ageMax) || 65,
        genders: gender === "all" ? [] : [Number(gender)],
        publisher_platforms: Array.from(platforms),
      },
      creative:
        source === "post"
          ? { source: "post", post_target_id: postTargetId }
          : {
              source: mediaRef.startsWith("studio:") ? "studio" : "upload",
              media_ref: mediaRef,
              page_account_id: pageId,
              instagram_account_id: instagramId || null,
              message: text.trim(),
              headline: headline.trim(),
              link_url: linkUrl.trim(),
              call_to_action: cta,
            },
      client_idempotency_key: idempotencyKey,
    };
    setBusy("create");
    try {
      await createAdsCampaign(input);
      setMessage(t("create.created"));
      setIdempotencyKey(newKey());
      setName("");
      setBudget("");
      await load();
    } catch (cause) {
      setError(adsErrorText(t, cause));
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function run(key: string, work: () => Promise<unknown>, success?: string) {
    setError("");
    setMessage("");
    setBusy(key);
    try {
      await work();
      if (success) setMessage(success);
      await load();
    } catch (cause) {
      setError(adsErrorText(t, cause));
    } finally {
      setBusy(null);
    }
  }

  function campaignBudget(item: AdsCampaign): number {
    return item.daily_budget_minor ?? item.lifetime_budget_minor ?? 0;
  }

  async function confirmActivation() {
    if (!activating) return;
    const target = activating;
    await run(
      `activate:${target.id}`,
      () =>
        activateAdsCampaign(target.id, {
          confirmation: phrase,
          confirmed_budget_minor: toMinor(confirmBudget, target.currency),
        }),
      t("activate.done"),
    );
    setActivating(null);
    setPhrase("");
    setConfirmBudget("");
  }

  const inputClass = "glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none";

  return (
    <div className="space-y-6">
      {message && <StatusMessage tone="success">{message}</StatusMessage>}
      {error && <StatusMessage tone="error">{error}</StatusMessage>}

      <section className="glass-card p-6 md:p-8">
        <h2 className="text-xl font-semibold text-white">{t("create.title")}</h2>
        <p className="mt-1 text-sm text-white/45">{t("create.description")}</p>
        <p className="mt-2 text-xs text-white/40">
          {t("create.caps", {
            daily: moneyMinor(access.daily_cap_minor, currency),
            lifetime: moneyMinor(access.lifetime_cap_minor, currency),
          })}
        </p>
        <form onSubmit={submit} className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-2 md:col-span-2">
            <span className="text-xs text-white/50">{t("create.name")}</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} className={inputClass} />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("dashboard.account")}</span>
            <select value={link?.id ?? ""} onChange={(e) => setLinkId(e.target.value)} className={inputClass}>
              {links.map((item) => (
                <option key={item.id} value={item.id} className="bg-obsidian-900">{item.name} · {item.currency}</option>
              ))}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("create.objective")}</span>
            <select value={objective} onChange={(e) => setObjective(e.target.value as AdsObjective)} className={inputClass}>
              {OBJECTIVES.map((value) => (
                <option key={value} value={value} className="bg-obsidian-900">{t(`objective.${value}`)}</option>
              ))}
            </select>
          </label>
          <p className="text-[11px] text-white/35 md:col-span-2 xl:col-span-4">{t("create.objectiveNote")}</p>

          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("create.budgetType")}</span>
            <select value={budgetType} onChange={(e) => setBudgetType(e.target.value as "daily" | "lifetime")} className={inputClass}>
              <option value="daily" className="bg-obsidian-900">{t("create.daily")}</option>
              <option value="lifetime" className="bg-obsidian-900">{t("create.lifetime")}</option>
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("create.budget", { currency })}</span>
            <input inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} className={inputClass} />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("create.start")}</span>
            <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} className={inputClass} />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("create.end")}</span>
            <input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} className={inputClass} />
          </label>

          <label className="space-y-2 md:col-span-2">
            <span className="text-xs text-white/50">{t("create.countries")}</span>
            <input value={countries} onChange={(e) => setCountries(e.target.value)} placeholder="AE,SA,EG" className={inputClass} />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("create.ageMin")}</span>
            <input inputMode="numeric" value={ageMin} onChange={(e) => setAgeMin(e.target.value)} className={inputClass} />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("create.ageMax")}</span>
            <input inputMode="numeric" value={ageMax} onChange={(e) => setAgeMax(e.target.value)} className={inputClass} />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("create.gender")}</span>
            <select value={gender} onChange={(e) => setGender(e.target.value as "all" | "1" | "2")} className={inputClass}>
              <option value="all" className="bg-obsidian-900">{t("create.genderAll")}</option>
              <option value="1" className="bg-obsidian-900">{t("create.genderMale")}</option>
              <option value="2" className="bg-obsidian-900">{t("create.genderFemale")}</option>
            </select>
          </label>
          <fieldset className="space-y-2 md:col-span-1 xl:col-span-3">
            <legend className="text-xs text-white/50">{t("create.platforms")}</legend>
            <div className="flex gap-4 pt-2 text-sm text-white/75">
              {(["facebook", "instagram"] as const).map((platform) => (
                <label key={platform} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={platforms.has(platform)}
                    onChange={() =>
                      setPlatforms((current) => {
                        const next = new Set(current);
                        if (next.has(platform)) next.delete(platform);
                        else next.add(platform);
                        return next;
                      })
                    }
                  />
                  {platform === "facebook" ? "Facebook" : "Instagram"}
                </label>
              ))}
            </div>
          </fieldset>

          <label className="space-y-2 md:col-span-2 xl:col-span-4">
            <span className="text-xs text-white/50">{t("create.creativeSource")}</span>
            <select value={source} onChange={(e) => setSource(e.target.value as "post" | "upload")} className={inputClass}>
              <option value="post" className="bg-obsidian-900">{t("source.post")}</option>
              <option value="upload" className="bg-obsidian-900" disabled={objective === "engagement"}>{t("source.upload")}</option>
            </select>
          </label>

          {source === "post" ? (
            <label className="space-y-2 md:col-span-2 xl:col-span-4">
              <span className="text-xs text-white/50">{t("create.post")}</span>
              {posts.length ? (
                <select value={postTargetId} onChange={(e) => setPostTargetId(e.target.value)} className={inputClass}>
                  <option value="" className="bg-obsidian-900">—</option>
                  {posts.map((target) => (
                    <option key={target.id} value={target.id} className="bg-obsidian-900">
                      {target.account_name} · {target.provider} · {target.published_at ? new Date(target.published_at).toLocaleDateString() : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <p className="text-xs text-white/35">{t("create.noPosts")}</p>
              )}
            </label>
          ) : (
            <>
              <label className="space-y-2 md:col-span-2">
                <span className="text-xs text-white/50">{t("create.media")}</span>
                {media.length ? (
                  <select value={mediaRef} onChange={(e) => setMediaRef(e.target.value)} className={inputClass}>
                    <option value="" className="bg-obsidian-900">—</option>
                    {media.map((item) => (
                      <option key={item.ref} value={item.ref} className="bg-obsidian-900">{item.title || item.filename}</option>
                    ))}
                  </select>
                ) : (
                  <p className="text-xs text-white/35">{t("create.noMedia")}</p>
                )}
              </label>
              <label className="space-y-2">
                <span className="text-xs text-white/50">{t("create.page")}</span>
                <select value={pageId} onChange={(e) => setPageId(e.target.value)} className={inputClass}>
                  <option value="" className="bg-obsidian-900">—</option>
                  {facebookPages.map((item) => (
                    <option key={item.id} value={item.id} className="bg-obsidian-900">{item.display_name}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-2">
                <span className="text-xs text-white/50">{t("create.instagram")}</span>
                <select value={instagramId} onChange={(e) => setInstagramId(e.target.value)} className={inputClass}>
                  <option value="" className="bg-obsidian-900">{t("none")}</option>
                  {instagramAccounts.map((item) => (
                    <option key={item.id} value={item.id} className="bg-obsidian-900">{item.handle || item.display_name}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 md:col-span-2">
                <span className="text-xs text-white/50">{t("create.headline")}</span>
                <input value={headline} onChange={(e) => setHeadline(e.target.value)} maxLength={120} className={inputClass} />
              </label>
              <label className="space-y-2">
                <span className="text-xs text-white/50">{t("create.link")}</span>
                <input value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} placeholder="https://" className={inputClass} />
              </label>
              <label className="space-y-2">
                <span className="text-xs text-white/50">{t("create.cta")}</span>
                <select value={cta} onChange={(e) => setCta(e.target.value)} className={inputClass}>
                  {CTAS.map((value) => (
                    <option key={value} value={value} className="bg-obsidian-900">{value.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 md:col-span-2 xl:col-span-4">
                <span className="text-xs text-white/50">{t("create.message")}</span>
                <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={2000} className={inputClass} />
              </label>
            </>
          )}

          <div className="md:col-span-2 xl:col-span-4">
            <Button type="submit" disabled={busy === "create" || !links.length}>
              {busy === "create" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {busy === "create" ? t("create.submitting") : t("create.submit")}
            </Button>
          </div>
        </form>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold text-white">{t("list.title")}</h2>
        {campaigns.length === 0 ? (
          <div className="glass-card p-6 text-center text-sm text-white/40">{t("list.empty")}</div>
        ) : (
          campaigns.map((item) => {
            const status = STATUSES.includes(item.status) ? item.status : "failed";
            const live = item.status === "active";
            return (
              <article key={item.id} className="glass-card p-5">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="text-sm font-semibold text-white">{item.name}</div>
                    <div className="mt-1 text-xs text-white/40">
                      {t(`objective.${OBJECTIVES.includes(item.objective as AdsObjective) ? item.objective : "traffic"}`)} ·{" "}
                      {moneyMinor(item.daily_budget_minor ?? item.lifetime_budget_minor, item.currency)}{" "}
                      {item.daily_budget_minor != null ? t("create.daily") : t("create.lifetime")}
                    </div>
                    <div className="mt-1 text-[11px] text-white/35">
                      {t("list.spendToday", { value: money(item.spend_today, item.currency) })} ·{" "}
                      {t("list.spendTotal", { value: money(item.spend_to_date, item.currency) })}
                    </div>
                    {item.pause_reason && item.status === "auto_paused" && (
                      <div className="mt-1 text-[11px] text-amber-200/70">{t("list.reason", { value: item.pause_reason })}</div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-2.5 py-1 text-[11px] ${
                        live
                          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-200"
                          : status === "failed" || status === "auto_paused"
                            ? "border-rose-500/25 bg-rose-500/10 text-rose-200"
                            : "border-white/10 bg-white/[0.04] text-white/60"
                      }`}
                    >
                      {t(`status.${status}`)}
                    </span>
                    {(item.status === "paused" || item.status === "auto_paused") && (
                      <Button size="sm" disabled={busy !== null || !access.activation_enabled} onClick={() => setActivating(item)}>
                        <Play className="h-3.5 w-3.5" /> {t("list.activate")}
                      </Button>
                    )}
                    {live && (
                      <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void run(`pause:${item.id}`, () => pauseAdsCampaign(item.id))}>
                        <Pause className="h-3.5 w-3.5" /> {t("list.pause")}
                      </Button>
                    )}
                    {(item.status === "failed" || item.status === "draft") && (
                      <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void run(`provision:${item.id}`, () => provisionAdsCampaign(item.id))}>
                        <RotateCcw className="h-3.5 w-3.5" /> {t("list.retry")}
                      </Button>
                    )}
                  </div>
                </div>
              </article>
            );
          })
        )}
        {!access.activation_enabled && <p className="text-xs text-white/40">{t("activate.disabled")}</p>}
      </section>

      {activating && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="glass-card w-full max-w-lg p-6">
            <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
              <ShieldAlert className="h-5 w-5 text-crimson-300" />
              {t("activate.title", { name: activating.name })}
            </h3>
            <p className="mt-2 text-sm leading-6 text-white/60">
              {t("activate.body", { budget: moneyMinor(campaignBudget(activating), activating.currency) })}
            </p>
            <label className="mt-4 block space-y-2">
              <span className="text-xs text-white/50">{t("activate.phrase", { phrase: access.activation_phrase })}</span>
              <input value={phrase} onChange={(e) => setPhrase(e.target.value)} autoComplete="off" dir="ltr" className={inputClass} />
            </label>
            <label className="mt-3 block space-y-2">
              <span className="text-xs text-white/50">{t("activate.budget", { currency: activating.currency })}</span>
              <input
                inputMode="decimal"
                value={confirmBudget}
                onChange={(e) => setConfirmBudget(e.target.value)}
                placeholder={String(campaignBudget(activating) / currencyOffset(activating.currency))}
                className={inputClass}
              />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setActivating(null)}>{t("activate.cancel")}</Button>
              <Button
                disabled={phrase.trim() !== access.activation_phrase || busy !== null}
                onClick={() => void confirmActivation()}
              >
                {t("activate.confirm")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
