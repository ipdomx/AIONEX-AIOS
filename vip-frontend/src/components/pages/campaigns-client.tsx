"use client";

import {
  BadgeCheck,
  BarChart3,
  BrainCircuit,
  CircleDollarSign,
  LoaderCircle,
  Megaphone,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Plus,
  Wallet,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  getAdsAccess,
  getPaidCampaignReadiness,
  listAdAccountLinks,
  listPaidCampaigns,
  prepareAndSimulatePaidCampaign,
} from "@/lib/api";
import type {
  AdAccountLink,
  AdsAccess,
  PaidCampaign,
  PaidCampaignAdAccount,
  PaidCampaignBudgetAssessment,
  PaidCampaignPreparationResult,
  PaidCampaignReadiness,
} from "@/types";

import { AdsAccountsPanel } from "./ads-accounts-panel";
import { AdsCampaignBuilder } from "./ads-campaign-builder";
import { AdsDashboardPanel } from "./ads-dashboard";

type CampaignTab = "dashboard" | "accounts" | "create" | "planning";

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

function moneyMinor(value: string): number {
  const parsed = Number(value.trim());
  if (!Number.isFinite(parsed) || parsed <= 0) return 0;
  return Math.round(parsed * 100);
}

function amount(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value / 100);
  } catch {
    return `${currency} ${(value / 100).toFixed(2)}`;
  }
}

const DELIVERY_STAGES = [
  ["aios_analysis", "stageAnalysis"],
  ["awaiting_owner", "stageAwaitingOwner"],
  ["owner_approved", "stageOwnerApproved"],
  ["live_plan_ready", "stageLivePlan"],
  ["provider_preparation", "stageProviderPreparing"],
  ["paused_on_meta", "stagePausedMeta"],
] as const;

function deliveryProgress(stage: PaidCampaign["delivery_stage"]): number {
  if (stage === "manual_review") return 4;
  const index = DELIVERY_STAGES.findIndex(([key]) => key === stage);
  return Math.max(0, index);
}

export function CampaignsClient() {
  const t = useTranslations("campaigns");
  const tAds = useTranslations("ads");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [campaigns, setCampaigns] = useState<PaidCampaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PaidCampaignPreparationResult | null>(null);
  const [readiness, setReadiness] = useState<PaidCampaignReadiness | null>(null);
  const [linkedAccountId, setLinkedAccountId] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [adsAccess, setAdsAccess] = useState<AdsAccess | null>(null);
  const [adsLinks, setAdsLinks] = useState<AdAccountLink[]>([]);
  const [tab, setTab] = useState<CampaignTab | null>(null);
  const [connectNotice, setConnectNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const [name, setName] = useState("");
  const [objective, setObjective] = useState("traffic");
  const [totalBudget, setTotalBudget] = useState("");
  const [dailyBudget, setDailyBudget] = useState("");
  const [maxCpa, setMaxCpa] = useState("");
  const [minRoas, setMinRoas] = useState("");
  const [countries, setCountries] = useState("");
  const [placements, setPlacements] = useState("feed");
  const [headline, setHeadline] = useState("");
  const [body, setBody] = useState("");
  const [destinationUrl, setDestinationUrl] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const loadAdsLinks = useCallback(async () => {
    setAdsLinks((await listAdAccountLinks()).items);
  }, []);

  const load = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError("");
    try {
      // GS-12 owner-reviewed planning and P4 Meta Ads management are gated
      // independently; the page opens when either is available.
      const access = await getPaidCampaignReadiness().catch(() => null);
      const ads =
        access === null || access.ads_management_visible
          ? await getAdsAccess().catch(() => null)
          : null;
      setReadiness(access);
      setAdsAccess(ads);
      if (!access && !ads) {
        setError(t("loadError"));
        return;
      }
      if (!access?.campaigns_visible && !ads?.allowed) {
        setCampaigns([]);
        setResult(null);
        router.replace(`/${locale}/dashboard`);
        return;
      }
      setTab((current) => current ?? (ads?.allowed ? "dashboard" : "planning"));
      if (access?.campaigns_visible) {
        setLinkedAccountId((current) =>
          access.linked_ad_accounts.some((item) => item.id === current)
            ? current
            : (access.linked_ad_accounts[0]?.id ?? ""),
        );
        setCampaigns(await listPaidCampaigns());
      }
      if (ads?.allowed) await loadAdsLinks();
    } catch (cause) {
      setError(errorText(cause, t("loadError")));
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, [isAuthenticated, loadAdsLinks, locale, router, t]);

  // The Meta ads-permission callback lands here; read it once and clear it.
  useEffect(() => {
    if (!isAuthenticated) return;
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get("result");
    if (!outcome || params.get("connect") !== "meta") return;
    setTab("accounts");
    setConnectNotice(
      outcome === "success"
        ? { tone: "success", text: tAds("accounts.connectSuccess") }
        : { tone: "error", text: tAds("accounts.connectError") },
    );
    window.history.replaceState(window.history.state, "", window.location.pathname);
  }, [isAuthenticated, tAds]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedAccount = useMemo<PaidCampaignAdAccount | null>(
    () =>
      readiness?.linked_ad_accounts.find((item) => item.id === linkedAccountId) ??
      readiness?.linked_ad_accounts[0] ??
      null,
    [linkedAccountId, readiness],
  );

  const pendingCount = useMemo(
    () => campaigns.filter((item) => item.approval_status !== "approved").length,
    [campaigns],
  );

  function recommendationText(assessment: PaidCampaignBudgetAssessment) {
    switch (assessment.recommendation) {
      case "increase_candidate":
        return t("recommendIncrease");
      case "decrease_or_rework":
        return t("recommendDecrease");
      case "keep_and_measure":
        return t("recommendHold");
      default:
        return t("recommendRework");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setResult(null);

    const total = moneyMinor(totalBudget);
    const daily = moneyMinor(dailyBudget);
    const cpa = maxCpa.trim() ? moneyMinor(maxCpa) : 0;
    const roas = minRoas.trim() ? Number(minRoas) : 0;
    if (!name.trim() || !total || !daily || daily > total) {
      setError(t("invalidBudget"));
      return;
    }
    if (!selectedAccount) {
      setError(t("accountRequired"));
      return;
    }
    if (maxCpa.trim() && !cpa) {
      setError(t("invalidCpa"));
      return;
    }
    if (minRoas.trim() && (!Number.isFinite(roas) || roas <= 0)) {
      setError(t("invalidRoas"));
      return;
    }

    const targetCountries = countries
      .split(",")
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
    const placementList = placements
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean);
    if (!targetCountries.length) {
      setError(t("countryRequired"));
      return;
    }

    setSubmitting(true);
    try {
      const prepared = await prepareAndSimulatePaidCampaign({
        campaign_name: name.trim(),
        objective,
        social_account_id: selectedAccount.id,
        total_budget_minor: total,
        daily_budget_cap_minor: daily,
        max_cpa_minor: cpa || null,
        min_roas: roas || null,
        target_countries: targetCountries,
        placements: placementList.length ? placementList : ["feed"],
        headline: headline.trim(),
        body: body.trim(),
        destination_url: destinationUrl.trim() || null,
        days: 3,
      });
      setResult(prepared);
      await load();
    } catch (cause) {
      setError(errorText(cause, t("submitError")));
    } finally {
      setSubmitting(false);
    }
  }

  if (isLoading || !isAuthenticated || !loaded) {
    return (
      <div className="page-shell py-16">
        <div className="glass-card p-8 text-center text-white/55">
          <LoaderCircle className="mx-auto h-5 w-5 animate-spin" />
          <p className="mt-3">{t("loading")}</p>
        </div>
      </div>
    );
  }

  const planningVisible = Boolean(readiness?.campaigns_visible);
  const adsVisible = Boolean(adsAccess?.allowed);
  if (!planningVisible && !adsVisible) {
    return error ? (
      <div className="page-shell py-16">
        <StatusMessage tone="error">{error}</StatusMessage>
      </div>
    ) : null;
  }
  const tabs: { key: CampaignTab; label: string; icon: typeof BarChart3 }[] = [
    ...(adsVisible
      ? [
          { key: "dashboard" as const, label: tAds("tabs.dashboard"), icon: BarChart3 },
          { key: "accounts" as const, label: tAds("tabs.accounts"), icon: Wallet },
          { key: "create" as const, label: tAds("tabs.create"), icon: Plus },
        ]
      : []),
    ...(planningVisible ? [{ key: "planning" as const, label: tAds("tabs.planning"), icon: Sparkles }] : []),
  ];
  const activeTab = tabs.some((item) => item.key === tab) ? (tab as CampaignTab) : tabs[0].key;

  return (
    <div className="page-shell space-y-6 py-10">
      <section className="glass-card overflow-hidden p-6 md:p-8">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-crimson-300/20 bg-crimson-500/10 px-3 py-1 text-xs text-crimson-200">
              <Megaphone className="h-3.5 w-3.5" /> {t("eyebrow")}
            </div>
            <h1 className="mt-4 text-3xl font-bold text-white md:text-4xl">{t("title")}</h1>
            <p className="mt-3 text-sm leading-7 text-white/50">{t("description")}</p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-white/70 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("refresh")}
          </button>
        </div>

        {activeTab === "planning" && <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
            <CircleDollarSign className="h-4 w-4 text-crimson-300" />
            <div className="mt-2 text-2xl font-bold text-white">{campaigns.length}</div>
            <div className="text-xs text-white/35">{t("campaignCount")}</div>
          </div>
          <div className="rounded-xl border border-orange-500/15 bg-orange-500/[0.04] p-4">
            <ShieldCheck className="h-4 w-4 text-orange-300" />
            <div className="mt-2 text-2xl font-bold text-white">{pendingCount}</div>
            <div className="text-xs text-white/35">{t("pendingOwner")}</div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <BrainCircuit className="h-4 w-4 text-zinc-300" />
            <div className="mt-2 text-sm font-semibold text-white">AIOS</div>
            <div className="mt-1 text-xs text-white/35">{t("adviceOnly")}</div>
          </div>
        </div>}

        {tabs.length > 1 && (
          <div role="tablist" className="mt-6 flex flex-wrap gap-2">
            {tabs.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.key}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === item.key}
                  onClick={() => setTab(item.key)}
                  className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-sm transition ${
                    activeTab === item.key
                      ? "border-crimson-400/40 bg-crimson-500/10 text-white"
                      : "border-white/10 bg-white/[0.03] text-white/55 hover:text-white"
                  }`}
                >
                  <Icon className="h-4 w-4" /> {item.label}
                </button>
              );
            })}
          </div>
        )}
      </section>

      {error && <StatusMessage tone="error">{error}</StatusMessage>}

      {adsVisible && activeTab !== "planning" && (
        <p className="text-xs leading-5 text-white/35">{tAds("liveNotice")}</p>
      )}
      {adsAccess && activeTab === "dashboard" && <AdsDashboardPanel links={adsLinks} />}
      {adsAccess && activeTab === "accounts" && (
        <AdsAccountsPanel access={adsAccess} links={adsLinks} onChanged={loadAdsLinks} notice={connectNotice} />
      )}
      {adsAccess && activeTab === "create" && <AdsCampaignBuilder access={adsAccess} links={adsLinks} />}

      {activeTab === "planning" && (
      <>

      <section className="glass-card p-6 md:p-8">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-1 h-5 w-5 text-crimson-300" />
          <div>
            <h2 className="text-xl font-semibold text-white">{t("createTitle")}</h2>
            <p className="mt-1 text-sm text-white/45">{t("createDescription")}</p>
          </div>
        </div>

        <form onSubmit={submit} className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-2 md:col-span-2">
            <span className="text-xs text-white/50">{t("name")}</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" placeholder={t("namePlaceholder")} />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("objective")}</span>
            <select value={objective} onChange={(e) => setObjective(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none">
              {[
                ["sales", "objectiveSales"],
                ["leads", "objectiveLeads"],
                ["traffic", "objectiveTraffic"],
                ["awareness", "objectiveAwareness"],
              ].map(([value, label]) => {
                const liveReady = selectedAccount?.live_objectives.includes(value);
                return (
                  <option key={value} className="bg-obsidian-900" value={value}>
                    {t(label)} — {liveReady ? t("objectiveLiveReady") : t("objectiveAnalysisOnly")}
                  </option>
                );
              })}
            </select>
            <span className="block text-[11px] leading-5 text-white/35">{t("objectiveSupportNote")}</span>
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("adAccount")}</span>
            <select value={selectedAccount?.id ?? ""} onChange={(e) => setLinkedAccountId(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none">
              {readiness?.linked_ad_accounts.map((account) => (
                <option key={account.id} className="bg-obsidian-900" value={account.id}>{account.display_name} · {account.provider}</option>
              ))}
            </select>
          </label>
          <div className="space-y-2">
            <span className="text-xs text-white/50">{t("linkedProvider")}</span>
            <div className="glass-input min-h-[48px] w-full rounded-xl px-4 py-3 text-sm text-white/75">{selectedAccount?.provider ?? "—"}</div>
          </div>
          <div className="space-y-2">
            <span className="text-xs text-white/50">{t("accountCurrency")}</span>
            <div className="glass-input min-h-[48px] w-full rounded-xl px-4 py-3 text-sm font-semibold text-white/75">{selectedAccount?.currency ?? "—"}</div>
          </div>

          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("totalBudget")}</span>
            <input inputMode="decimal" value={totalBudget} onChange={(e) => setTotalBudget(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("dailyBudget")}</span>
            <input inputMode="decimal" value={dailyBudget} onChange={(e) => setDailyBudget(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("maxCpa")}</span>
            <input inputMode="decimal" value={maxCpa} onChange={(e) => setMaxCpa(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" />
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("minRoas")}</span>
            <input inputMode="decimal" value={minRoas} onChange={(e) => setMinRoas(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" />
          </label>

          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("countries")}</span>
            <input value={countries} onChange={(e) => setCountries(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" placeholder="AE,SA" />
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-xs text-white/50">{t("placements")}</span>
            <input value={placements} onChange={(e) => setPlacements(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" placeholder="feed,stories" />
          </label>

          <label className="space-y-2 md:col-span-2">
            <span className="text-xs text-white/50">{t("headline")}</span>
            <input value={headline} onChange={(e) => setHeadline(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" />
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-xs text-white/50">{t("destinationUrl")}</span>
            <input value={destinationUrl} onChange={(e) => setDestinationUrl(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" placeholder="https://" />
          </label>
          <label className="space-y-2 md:col-span-2 xl:col-span-4">
            <span className="text-xs text-white/50">{t("body")}</span>
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={4} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" />
          </label>

          <div className="md:col-span-2 xl:col-span-4 rounded-xl border border-white/10 bg-white/[0.03] p-4 text-xs leading-6 text-white/45">
            {t("freedomNotice")}
          </div>
          <div className="md:col-span-2 xl:col-span-4">
            <Button type="submit" disabled={submitting} className="w-full md:w-auto">
              {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {submitting ? t("analyzing") : t("analyze")}
            </Button>
          </div>
        </form>
      </section>

      {result && (
        <section className="glass-card border border-white/10 p-6 md:p-8">
          <div className="flex items-start gap-3">
            <BrainCircuit className="mt-1 h-5 w-5 text-zinc-300" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-white">{t("analysisTitle")}</h2>
              <p className="mt-1 text-sm text-white/45">{t("analysisDescription")}</p>
              <p className="mt-2 text-xs leading-5 text-amber-200/70">{t("simulationDisclaimer")}</p>
            </div>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-white/[0.06] p-4">
              <div className="text-xs text-white/35">{t("recommendation")}</div>
              <div className="mt-2 text-sm font-semibold text-crimson-200">{recommendationText(result.budget_assessment)}</div>
            </div>
            <div className="rounded-xl border border-white/[0.06] p-4">
              <div className="text-xs text-white/35">{t("simulatedCpa")}</div>
              <div className="mt-2 text-sm font-semibold text-white">
                {result.budget_assessment.observed_cpa_minor == null ? "—" : amount(result.budget_assessment.observed_cpa_minor, result.campaign.currency)}
              </div>
            </div>
            <div className="rounded-xl border border-white/[0.06] p-4">
              <div className="text-xs text-white/35">{t("simulatedRoas")}</div>
              <div className="mt-2 text-sm font-semibold text-white">{result.budget_assessment.observed_roas.toFixed(2)}</div>
            </div>
            <div className="rounded-xl border border-orange-500/15 bg-orange-500/[0.04] p-4">
              <div className="text-xs text-orange-200/70">{t("status")}</div>
              <div className="mt-2 text-sm font-semibold text-orange-200">{t("awaitingOwner")}</div>
            </div>
          </div>
          <div className="mt-4 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 text-sm leading-7 text-white/55">
            <BadgeCheck className="mr-2 inline h-4 w-4 text-green-300" />
            {t("analysisSafety")}
          </div>
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-xl font-semibold text-white">{t("historyTitle")}</h2>
        {loading ? (
          <div className="glass-card p-6 text-center text-white/40">{t("loading")}</div>
        ) : campaigns.length === 0 ? (
          <div className="glass-card p-6 text-center text-white/40">{t("empty")}</div>
        ) : (
          campaigns.map((campaign) => (
            <article key={campaign.id} className="glass-card p-5">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <div className="text-sm font-semibold text-white">{campaign.name}</div>
                  <div className="mt-1 text-xs text-white/35">{campaign.objective} · {amount(campaign.total_budget_minor, campaign.currency)} · {t("dailyShort")} {amount(campaign.daily_budget_cap_minor, campaign.currency)}</div>
                </div>
                <span className={`rounded-full border px-2.5 py-1 text-[11px] ${campaign.approval_status === "approved" ? "border-green-500/20 bg-green-500/10 text-green-300" : "border-orange-500/20 bg-orange-500/10 text-orange-300"}`}>
                  {campaign.approval_status === "approved" ? t("approved") : t("awaitingOwner")}
                </span>
              </div>
              <div className="mt-4 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                <div className="text-xs font-semibold text-white/70">{t("deliveryTitle")}</div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {DELIVERY_STAGES.map(([key, label], index) => {
                    const reached = index <= deliveryProgress(campaign.delivery_stage);
                    const current = campaign.delivery_stage === key;
                    return (
                      <div
                        key={key}
                        className={`rounded-lg border px-3 py-2 text-[11px] ${
                          current
                            ? "border-crimson-400/30 bg-crimson-500/10 text-crimson-100"
                            : reached
                              ? "border-green-500/15 bg-green-500/[0.05] text-green-200/80"
                              : "border-white/[0.05] text-white/25"
                        }`}
                      >
                        <span className="mr-1.5 font-mono text-[10px]">{index + 1}</span>
                        {t(label)}
                      </div>
                    );
                  })}
                </div>
                {campaign.delivery_stage === "paused_on_meta" ? (
                  <div className="mt-3 rounded-lg border border-green-500/20 bg-green-500/[0.06] p-3 text-xs leading-5 text-green-200/80">
                    {t("pausedMetaNote")}
                  </div>
                ) : null}
                {campaign.manual_review_required ? (
                  <div className="mt-3 rounded-lg border border-rose-500/25 bg-rose-500/[0.07] p-3 text-xs leading-5 text-rose-200">
                    {t("manualReviewNote")}
                  </div>
                ) : null}
              </div>
              <div className="mt-3 text-xs text-white/35">{t("noAutoSpend")}</div>
            </article>
          ))
        )}
      </section>
      </>
      )}
    </div>
  );
}
