"use client";

import { AlertTriangle, BrainCircuit, LoaderCircle, RefreshCw, Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { createAdsRecommendations, getAdsAnalytics, getLatestAdsRecommendations } from "@/lib/api";
import type { AdAccountLink, AdsAlert, AdsCampaignMetrics, AdsDashboard, AdsRecommendationRun } from "@/types";

import { adsErrorText, BarList, compact, DeltaBadge, LineChart, money } from "./ads-shared";

const PERIODS = [7, 14, 30, 90] as const;
const KPI_KEYS = ["spend", "impressions", "clicks", "ctr", "cpc", "cpm", "conversions", "cpa", "roas", "frequency", "reach"] as const;
const MONEY_KPIS = new Set(["spend", "cpc", "cpm", "cpa"]);
const BREAKDOWNS = ["age", "gender", "platform_position", "country"] as const;
const RECOMMENDATION_TYPES = ["budget_shift", "creative_fatigue", "audience", "bid_or_schedule", "other"];

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function AdsDashboardPanel({ links }: { links: AdAccountLink[] }) {
  const t = useTranslations("ads");
  const locale = useLocale();
  const [linkId, setLinkId] = useState(links[0]?.id ?? "");
  const [days, setDays] = useState<(typeof PERIODS)[number]>(14);
  const [board, setBoard] = useState<AdsDashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [breakdown, setBreakdown] = useState<(typeof BREAKDOWNS)[number]>("age");
  const [table, setTable] = useState(false);
  const [advice, setAdvice] = useState<AdsRecommendationRun | null>(null);
  const [adviceBusy, setAdviceBusy] = useState(false);
  const [adviceError, setAdviceError] = useState("");
  const [consent, setConsent] = useState(false);

  useEffect(() => {
    if (!links.some((item) => item.id === linkId)) setLinkId(links[0]?.id ?? "");
  }, [links, linkId]);

  const link = links.find((item) => item.id === linkId) ?? null;

  const load = useCallback(async () => {
    if (!link) return;
    setLoading(true);
    setError("");
    try {
      const end = link.insights_synced_through ? new Date(`${link.insights_synced_through}T00:00:00Z`) : new Date();
      const start = new Date(end.getTime() - (days - 1) * 86_400_000);
      const [dashboard, latest] = await Promise.all([
        getAdsAnalytics(link.id, { from: isoDay(start), to: isoDay(end) }),
        getLatestAdsRecommendations(link.id),
      ]);
      setBoard(dashboard);
      setAdvice(latest.item);
    } catch (cause) {
      setError(adsErrorText(t, cause));
    } finally {
      setLoading(false);
    }
  }, [days, link, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function recommend() {
    if (!link) return;
    setAdviceBusy(true);
    setAdviceError("");
    try {
      setAdvice(
        await createAdsRecommendations({ link_id: link.id, language: locale, external_processing_confirmed: consent }),
      );
    } catch (cause) {
      setAdviceError(adsErrorText(t, cause));
    } finally {
      setAdviceBusy(false);
    }
  }

  const currency = board?.currency ?? link?.currency ?? "USD";
  const formatKpi = useCallback(
    (key: string, value: number | null) => {
      if (value == null) return "—";
      if (MONEY_KPIS.has(key)) return money(value, currency);
      if (key === "ctr") return `${compact(value)}%`;
      if (key === "roas" || key === "frequency") return compact(value);
      return compact(value, 0);
    },
    [currency],
  );

  const spendPoints = useMemo(
    () => (board?.trend ?? []).map((point) => ({ label: point.day, value: point.spend })),
    [board],
  );
  const conversionPoints = useMemo(
    () => (board?.trend ?? []).map((point) => ({ label: point.day, value: point.conversions })),
    [board],
  );

  function alertText(alert: AdsAlert): string {
    const e = alert.evidence;
    const num = (value: unknown) => (typeof value === "number" ? value : null);
    if (alert.type === "spend_spike")
      return t("alert.spend_spike", {
        day: String(e.day ?? ""),
        spend: money(num(e.spend), currency),
        average: money(num(e.average_prior_7_days), currency),
      });
    if (alert.type === "cpa_above_target")
      return t("alert.cpa_above_target", {
        name: alert.name ?? "",
        cpa: money(num(e.cpa_last_7_days), currency),
        target: money(num(e.cpa_target), currency),
      });
    return t("alert.frequency_fatigue", {
      name: alert.name ?? "",
      frequency: compact(num(e.frequency_last_7_days)),
      drop: compact(Math.abs(num(e.ctr_change_pct) ?? 0), 1),
    });
  }

  if (!links.length) {
    return <div className="glass-card p-6 text-center text-sm text-white/45">{t("dashboard.noAccount")}</div>;
  }

  const breakdownItems = (board?.breakdowns[breakdown] ?? []).map((item) => ({ label: item.value, value: item.spend }));

  return (
    <div className="space-y-6">
      <section className="glass-card flex flex-col gap-4 p-5 md:flex-row md:items-end md:justify-between">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("dashboard.account")}</span>
            <select value={linkId} onChange={(e) => setLinkId(e.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none">
              {links.map((item) => (
                <option key={item.id} value={item.id} className="bg-obsidian-900">
                  {item.name} · {item.currency}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-xs text-white/50">{t("dashboard.period")}</span>
            <select value={days} onChange={(e) => setDays(Number(e.target.value) as (typeof PERIODS)[number])} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none">
              {PERIODS.map((count) => (
                <option key={count} value={count} className="bg-obsidian-900">
                  {t("dashboard.days", { count })}
                </option>
              ))}
            </select>
          </label>
        </div>
        <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          {t("refresh")}
        </Button>
      </section>

      {error && <StatusMessage tone="error">{error}</StatusMessage>}
      {loading && !board && (
        <div className="glass-card p-6 text-center text-white/45">
          <LoaderCircle className="mx-auto h-5 w-5 animate-spin" />
        </div>
      )}

      {board && !board.has_data && <StatusMessage tone="info">{t("dashboard.noData")}</StatusMessage>}

      {board && (
        <>
          <p className="text-xs text-white/35">
            {t("dashboard.dataSource", { currency: board.currency })} · {board.period.from} → {board.period.to}
          </p>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
            {KPI_KEYS.map((key) => {
              const kpi = board.kpis[key];
              return (
                <div key={key} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                  <div className="text-xs text-white/40">{t(`kpi.${key}`)}</div>
                  <div className="mt-2 text-xl font-bold text-white">{formatKpi(key, kpi?.value ?? null)}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <DeltaBadge change={kpi?.change_pct ?? null} />
                    <span className="text-[10px] text-white/25">{t("dashboard.vsPrevious")}</span>
                  </div>
                </div>
              );
            })}
          </section>

          <section className="glass-card space-y-6 p-5">
            <div className="grid gap-6 lg:grid-cols-2">
              <LineChart points={spendPoints} title={t("dashboard.trendSpend")} format={(value) => money(value, currency)} />
              <LineChart points={conversionPoints} title={t("dashboard.trendConversions")} format={(value) => compact(value)} />
            </div>
            <button type="button" onClick={() => setTable((value) => !value)} className="text-xs text-crimson-200 underline-offset-4 hover:underline">
              {t("dashboard.tableView")}
            </button>
            {table && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-white/70">
                  <thead className="text-white/40">
                    <tr>
                      <th className="py-2 pe-4">{t("dashboard.day")}</th>
                      <th className="py-2 pe-4">{t("kpi.spend")}</th>
                      <th className="py-2 pe-4">{t("kpi.clicks")}</th>
                      <th className="py-2 pe-4">{t("kpi.conversions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {board.trend.map((point) => (
                      <tr key={point.day} className="border-t border-white/[0.05]">
                        <td className="py-1.5 pe-4">{point.day}</td>
                        <td className="py-1.5 pe-4">{money(point.spend, currency)}</td>
                        <td className="py-1.5 pe-4">{compact(point.clicks, 0)}</td>
                        <td className="py-1.5 pe-4">{compact(point.conversions)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="grid gap-6 lg:grid-cols-2">
            {(["top", "bottom"] as const).map((side) => (
              <div key={side} className="glass-card p-5">
                <h3 className="text-sm font-semibold text-white">{t(side === "top" ? "dashboard.top" : "dashboard.bottom")}</h3>
                <p className="mt-1 text-[11px] text-white/35">{t("dashboard.rankedBy", { metric: t(`kpi.${board.campaigns.basis}`) })}</p>
                <CampaignTable items={board.campaigns[side]} format={formatKpi} label={t("dashboard.campaign")} t={t} />
              </div>
            ))}
          </section>

          <section className="grid gap-6 lg:grid-cols-2">
            <div className="glass-card p-5">
              <h3 className="text-sm font-semibold text-white">{t("dashboard.breakdowns")}</h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {BREAKDOWNS.map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setBreakdown(key)}
                    className={`rounded-full border px-3 py-1 text-[11px] ${breakdown === key ? "border-crimson-400/40 bg-crimson-500/10 text-crimson-100" : "border-white/10 text-white/50"}`}
                  >
                    {t(`breakdown.${key}`)}
                  </button>
                ))}
              </div>
              <div className="mt-4">
                {breakdownItems.length ? (
                  <BarList items={breakdownItems} format={(value) => money(value, currency)} />
                ) : (
                  <p className="text-xs text-white/35">{t("dashboard.noBreakdown")}</p>
                )}
              </div>
            </div>
            <div className="glass-card p-5">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                <AlertTriangle className="h-4 w-4 text-orange-300" /> {t("dashboard.alerts")}
              </h3>
              {board.alerts.length ? (
                <ul className="mt-3 space-y-2">
                  {board.alerts.map((alert, index) => (
                    <li key={`${alert.type}-${alert.campaign_id ?? index}`} className="rounded-lg border border-orange-500/20 bg-orange-500/[0.05] p-3 text-xs leading-5 text-orange-100/90">
                      {alertText(alert)}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-xs text-white/35">{t("dashboard.noAlerts")}</p>
              )}
            </div>
          </section>
        </>
      )}

      <section className="glass-card p-5 md:p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="max-w-2xl">
            <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
              <BrainCircuit className="h-5 w-5 text-crimson-300" /> {t("ai.title")}
            </h3>
            <p className="mt-1 text-sm text-white/45">{t("ai.description")}</p>
            <label className="mt-3 flex items-center gap-2 text-xs text-white/50">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              {t("ai.externalConsent")}
            </label>
          </div>
          <Button onClick={() => void recommend()} disabled={adviceBusy || !board?.has_data}>
            {adviceBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {adviceBusy ? t("ai.generating") : t("ai.generate")}
          </Button>
        </div>
        {adviceError && <StatusMessage tone="error" className="mt-4">{adviceError}</StatusMessage>}
        <p className="mt-4 text-xs text-amber-200/70">{t("ai.advisory")}</p>
        {advice ? (
          <div className="mt-4 space-y-3">
            <p className="text-[11px] text-white/35">
              {t("ai.model", { model: advice.model })} · {advice.period.from} → {advice.period.to}
            </p>
            {advice.items.length === 0 && <p className="text-sm text-white/40">{t("ai.empty")}</p>}
            {advice.items.map((item, index) => (
              <article key={`${item.type}-${index}`} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-crimson-400/25 bg-crimson-500/10 px-2 py-0.5 text-[10px] text-crimson-100">
                    {t(`aiType.${RECOMMENDATION_TYPES.includes(item.type) ? item.type : "other"}`)}
                  </span>
                  <h4 className="text-sm font-semibold text-white">{item.title}</h4>
                </div>
                <p className="mt-2 text-sm text-white/70">{item.action}</p>
                {item.rationale && <p className="mt-1 text-xs text-white/45">{item.rationale}</p>}
                <div className="mt-3 text-[11px] text-white/40">{t("ai.basedOn")}</div>
                <ul className="mt-1 flex flex-wrap gap-2">
                  {Object.entries(item.evidence).map(([key, value]) => (
                    <li key={key} className="rounded-md border border-white/10 bg-obsidian-800 px-2 py-1 font-mono text-[10px] text-white/70">
                      {key} = {compact(value, 4)}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
            {advice.rejected > 0 && <p className="text-[11px] text-white/35">{t("ai.rejected", { count: advice.rejected })}</p>}
          </div>
        ) : (
          <p className="mt-4 text-sm text-white/40">{t("ai.empty")}</p>
        )}
      </section>
    </div>
  );
}

function CampaignTable({
  items,
  format,
  label,
  t,
}: {
  items: AdsCampaignMetrics[];
  format: (key: string, value: number | null) => string;
  label: string;
  t: (key: string) => string;
}) {
  if (!items.length) return <p className="mt-3 text-xs text-white/35">—</p>;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-xs text-white/70">
        <thead className="text-white/40">
          <tr>
            <th className="py-2 pe-3">{label}</th>
            {(["spend", "ctr", "cpa", "roas"] as const).map((key) => (
              <th key={key} className="py-2 pe-3">{t(`kpi.${key}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.campaign_id} className="border-t border-white/[0.05]">
              <td className="max-w-[180px] truncate py-1.5 pe-3 text-white">{item.name}</td>
              {(["spend", "ctr", "cpa", "roas"] as const).map((key) => (
                <td key={key} className="py-1.5 pe-3">{format(key, item[key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
