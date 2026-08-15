"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  CircleDollarSign,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserRoundCheck,
} from "lucide-react";

import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import { translateInterfaceText } from "@/lib/interface-translations";
import {
  approveOwnerGrowthPaidCampaign,
  fetchOwnerGrowthPaidCampaigns,
  type OwnerGrowthPaidCampaign,
} from "@/lib/owner-growth-social";

function minorAmount(value: number, currency: string) {
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

function technicalText(value: unknown) {
  return String(value ?? "—").replaceAll("_", " ");
}

export function GrowthPaidCampaignApprovalConsole() {
  const { locale } = useLanguageVoice();
  const tr = useCallback(
    (text: string) => translateInterfaceText(text, locale),
    [locale],
  );
  const [items, setItems] = useState<OwnerGrowthPaidCampaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState("Loading paid campaign approvals…");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchOwnerGrowthPaidCampaigns();
      setItems(response.items);
      setMessage(`Loaded ${response.items.length} paid campaign records.`);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to load paid campaigns.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const pending = useMemo(
    () => items.filter((item) => item.approval_status !== "approved"),
    [items],
  );
  const approved = items.length - pending.length;

  async function approve(item: OwnerGrowthPaidCampaign) {
    const confirmed = window.confirm(
      tr(
        "Approve this campaign with the user's selected budget unchanged? Approval does not launch the campaign or authorize real spend.",
      ),
    );
    if (!confirmed) return;
    setBusyId(item.id);
    setMessage("Recording Super Owner campaign approval…");
    try {
      await approveOwnerGrowthPaidCampaign(item.id);
      setMessage(
        "Campaign approved by Super Owner. Budget remains unchanged and launch is still separate.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Campaign approval failed.",
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="glass-card overflow-hidden border border-violet-500/15">
      <div className="border-b border-white/[0.06] bg-violet-500/[0.04] p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-violet-500/20 bg-violet-500/10 px-3 py-1 text-xs text-violet-200">
              <UserRoundCheck className="h-3.5 w-3.5" />
              {tr("Paid Campaign Owner Approval")}
            </div>
            <h2 className="text-xl font-semibold text-white">
              {tr(
                "Users choose the budget; AIOS advises; the Super Owner approves",
              )}
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-white/40">
              {tr(
                "AIOS analyzes the user's chosen campaign values and recommends whether to increase, decrease, hold, or rework them. It never rewrites the user's budget automatically, and Owner approval never launches or spends by itself.",
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading || busyId !== null}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-xs text-white/70 disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
            />
            {tr("Refresh campaign approvals")}
          </button>
        </div>
      </div>

      <div className="grid gap-3 p-5 sm:grid-cols-3">
        <div className="rounded-xl border border-orange-500/15 bg-orange-500/[0.04] p-4">
          <ShieldCheck className="h-4 w-4 text-orange-300" />
          <div className="mt-2 text-2xl font-bold text-white">
            {pending.length}
          </div>
          <div className="text-xs text-white/35">
            {tr("Awaiting Owner approval")}
          </div>
        </div>
        <div className="rounded-xl border border-green-500/15 bg-green-500/[0.04] p-4">
          <CheckCircle2 className="h-4 w-4 text-green-300" />
          <div className="mt-2 text-2xl font-bold text-white">{approved}</div>
          <div className="text-xs text-white/35">{tr("Owner approved")}</div>
        </div>
        <div className="rounded-xl border border-electric-500/15 bg-electric-500/[0.04] p-4">
          <Sparkles className="h-4 w-4 text-electric-300" />
          <div className="mt-2 text-sm font-semibold text-white">AIOS</div>
          <div className="mt-1 text-xs text-white/35">
            {tr("Advisory only — never automatic")}
          </div>
        </div>
      </div>

      <div className="space-y-3 px-5 pb-5">
        {loading ? (
          <div className="rounded-xl border border-white/[0.06] p-6 text-center text-sm text-white/35">
            {tr("Loading paid campaign approvals…")}
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-xl border border-white/[0.06] p-6 text-center text-sm text-white/35">
            {tr("No paid campaigns are waiting for review.")}
          </div>
        ) : (
          items.map((item) => {
            const assessment = item.latest_budget_assessment ?? {};
            const isApproved = item.approval_status === "approved";
            return (
              <article
                key={item.id}
                className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
              >
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-white">
                        {item.name}
                      </span>
                      <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-white/45">
                        {technicalText(item.objective)}
                      </span>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] ${
                          isApproved
                            ? "border-green-500/20 bg-green-500/10 text-green-300"
                            : "border-orange-500/20 bg-orange-500/10 text-orange-300"
                        }`}
                      >
                        {isApproved
                          ? tr("Approved")
                          : tr("Awaiting Owner approval")}
                      </span>
                    </div>
                    <div className="mt-2 text-xs text-white/35">
                      {tr("User")}: {item.created_by_name || "—"} ·{" "}
                      {tr("Organization")}: {item.organization_name || "—"}
                    </div>

                    <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                      <div className="rounded-lg border border-white/[0.05] p-3">
                        <div className="text-[10px] uppercase tracking-wider text-white/30">
                          {tr("User total budget")}
                        </div>
                        <div className="mt-1 text-sm font-semibold text-white">
                          {minorAmount(item.total_budget_minor, item.currency)}
                        </div>
                      </div>
                      <div className="rounded-lg border border-white/[0.05] p-3">
                        <div className="text-[10px] uppercase tracking-wider text-white/30">
                          {tr("User daily budget")}
                        </div>
                        <div className="mt-1 text-sm font-semibold text-white">
                          {minorAmount(
                            item.daily_budget_cap_minor,
                            item.currency,
                          )}
                        </div>
                      </div>
                      <div className="rounded-lg border border-white/[0.05] p-3">
                        <div className="text-[10px] uppercase tracking-wider text-white/30">
                          {tr("AIOS recommendation")}
                        </div>
                        <div className="mt-1 text-xs font-medium text-electric-200">
                          {technicalText(assessment.recommendation)}
                        </div>
                      </div>
                      <div className="rounded-lg border border-white/[0.05] p-3">
                        <div className="text-[10px] uppercase tracking-wider text-white/30">
                          {tr("AIOS rationale")}
                        </div>
                        <div className="mt-1 text-xs text-white/55">
                          {technicalText(assessment.rationale)}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-col gap-2 xl:w-48">
                    <div className="rounded-lg border border-white/[0.06] bg-black/10 p-3 text-[11px] leading-5 text-white/35">
                      <CircleDollarSign className="mb-1 h-3.5 w-3.5 text-electric-300" />
                      {tr(
                        "Approval preserves the user's budget and does not authorize launch, provider mutation, or real spend.",
                      )}
                    </div>
                    <button
                      type="button"
                      disabled={isApproved || busyId !== null}
                      onClick={() => void approve(item)}
                      className="inline-flex items-center justify-center gap-2 rounded-lg bg-green-500/15 px-3 py-2 text-xs font-medium text-green-200 disabled:opacity-40"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      {isApproved
                        ? tr("Owner approved")
                        : tr("Approve campaign")}
                    </button>
                  </div>
                </div>
              </article>
            );
          })
        )}
      </div>

      <div className="border-t border-white/[0.06] px-5 py-3 text-xs text-electric-300">
        {tr(message)}
      </div>
    </section>
  );
}
