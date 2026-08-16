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
  evaluateOwnerGrowthPaidCampaignLivePlan,
  fetchOwnerGrowthMetaPages,
  fetchOwnerGrowthPaidCampaigns,
  fetchOwnerGrowthPilots,
  prepareOwnerGrowthPaidCampaignLivePlan,
  validateOwnerGrowthPaidCampaignLivePlan,
  type GrowthControlledPilot,
  type GrowthMetaPage,
  type OwnerGrowthPaidCampaign,
  type OwnerGrowthPaidLivePlan,
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
  const [livePanelId, setLivePanelId] = useState<string | null>(null);
  const [liveDataLoaded, setLiveDataLoaded] = useState(false);
  const [livePilots, setLivePilots] = useState<GrowthControlledPilot[]>([]);
  const [metaPages, setMetaPages] = useState<GrowthMetaPage[]>([]);
  const [planInputs, setPlanInputs] = useState<
    Record<string, { pilotId: string; pageRef: string }>
  >({});
  const [planResults, setPlanResults] = useState<
    Record<string, OwnerGrowthPaidLivePlan>
  >({});

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

  function updatePlanInput(
    campaignId: string,
    patch: Partial<{ pilotId: string; pageRef: string }>,
  ) {
    setPlanInputs((current) => ({
      ...current,
      [campaignId]: {
        pilotId: current[campaignId]?.pilotId ?? "",
        pageRef: current[campaignId]?.pageRef ?? "",
        ...patch,
      },
    }));
  }

  async function loadLiveSources() {
    const [pilotResponse, pageResponse] = await Promise.all([
      fetchOwnerGrowthPilots(),
      fetchOwnerGrowthMetaPages(),
    ]);
    setLivePilots(
      pilotResponse.items.filter(
        (pilot) => pilot.provider === "meta" && pilot.mode === "live_spend",
      ),
    );
    setMetaPages(pageResponse.pages.filter((page) => page.advertise_ready));
    setLiveDataLoaded(true);
    setMessage(
      `Loaded ${pilotResponse.items.length} controlled pilots and ${pageResponse.advertise_ready_page_count} Meta advertising Pages.`,
    );
  }

  async function toggleLivePlan(item: OwnerGrowthPaidCampaign) {
    if (livePanelId === item.id) {
      setLivePanelId(null);
      return;
    }
    setLivePanelId(item.id);
    if (liveDataLoaded) return;
    setBusyId(item.id);
    setMessage("Loading fail-closed live-plan sources…");
    try {
      await loadLiveSources();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to load live-plan sources.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function evaluatePlan(item: OwnerGrowthPaidCampaign) {
    const input = planInputs[item.id] ?? { pilotId: "", pageRef: "" };
    if (!input.pilotId) {
      setMessage("Select a controlled live-spend pilot before evaluating.");
      return;
    }
    setBusyId(item.id);
    setMessage(
      "Evaluating the campaign-to-pilot live plan without provider writes…",
    );
    try {
      const result = await evaluateOwnerGrowthPaidCampaignLivePlan(item.id, {
        pilot_id: input.pilotId,
        creative_identity_ref: input.pageRef || null,
      });
      setPlanResults((current) => ({ ...current, [item.id]: result }));
      setMessage(
        result.plan_compilable
          ? "Live plan is statically compilable. Launch and spend remain separate."
          : `Live plan remains blocked by ${result.blocked_reasons.length} gate(s).`,
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Live-plan evaluation failed.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function preparePlan(item: OwnerGrowthPaidCampaign) {
    const input = planInputs[item.id] ?? { pilotId: "", pageRef: "" };
    if (!input.pilotId || !input.pageRef) {
      setMessage(
        "Select both the controlled pilot and Meta Page before preparing.",
      );
      return;
    }
    const confirmed = window.confirm(
      tr(
        "Prepare a digest-bound live plan only? This does not call Meta, authorize launch, or spend money.",
      ),
    );
    if (!confirmed) return;
    setBusyId(item.id);
    setMessage("Preparing digest-bound live plan without provider calls…");
    try {
      const result = await prepareOwnerGrowthPaidCampaignLivePlan(item.id, {
        pilot_id: input.pilotId,
        creative_identity_ref: input.pageRef,
      });
      setPlanResults((current) => ({ ...current, [item.id]: result }));
      setMessage(
        "Live plan digest prepared. Runtime authorization and launch remain mandatory and separate.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Live-plan preparation failed.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function validatePlan(item: OwnerGrowthPaidCampaign) {
    setBusyId(item.id);
    setMessage("Revalidating the stored live-plan digest…");
    try {
      const result = await validateOwnerGrowthPaidCampaignLivePlan(item.id);
      setPlanResults((current) => ({ ...current, [item.id]: result }));
      setMessage(
        result.plan_valid
          ? "Stored live plan still matches the approved campaign configuration."
          : "Stored live plan no longer matches the campaign and cannot be used.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Live-plan validation failed.",
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
            const configuration = item.configuration_summary;
            const isApproved = item.approval_status === "approved";
            const candidatePilots = livePilots.filter(
              (pilot) => pilot.organization_id === item.organization_id,
            );
            const planInput = planInputs[item.id] ?? {
              pilotId: "",
              pageRef: "",
            };
            const planResult = planResults[item.id];
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

                    {configuration ? (
                      <div className="mt-3 rounded-xl border border-white/[0.06] bg-black/10 p-3">
                        <div className="text-[10px] uppercase tracking-wider text-white/30">
                          {tr("Campaign configuration reviewed by Owner")}
                        </div>
                        <div className="mt-2 grid gap-2 text-xs text-white/55 sm:grid-cols-3">
                          <div>
                            {tr("Platforms")}:{" "}
                            {configuration.providers.join(", ") || "—"}
                          </div>
                          <div>
                            {tr("Target countries")}:{" "}
                            {configuration.target_countries.join(", ") || "—"}
                          </div>
                          <div>
                            {tr("Placements")}:{" "}
                            {configuration.placements.join(", ") || "—"}
                          </div>
                        </div>
                        <div className="mt-2 text-[11px] text-white/35">
                          {tr("Ad sets")}: {configuration.ad_set_count} ·{" "}
                          {tr("Creatives")}: {configuration.creative_count} ·{" "}
                          {tr("Ads")}: {configuration.ad_count}
                        </div>
                        <div className="mt-3 space-y-2">
                          {configuration.creatives.map(
                            (creative, creativeIndex) => (
                              <div
                                key={`${item.id}-creative-${creativeIndex}`}
                                className="rounded-lg border border-white/[0.05] p-3"
                              >
                                <div className="text-[10px] text-white/30">
                                  {tr("Creative")} {creativeIndex + 1} ·{" "}
                                  {technicalText(creative.format)}
                                </div>
                                <div className="mt-1 text-xs font-medium text-white/75">
                                  {creative.headline || "—"}
                                </div>
                                <div className="mt-1 whitespace-pre-wrap text-xs text-white/50">
                                  {creative.body || "—"}
                                </div>
                                <div className="mt-1 break-all text-[11px] text-electric-200/70">
                                  {creative.destination_url || "—"}
                                </div>
                              </div>
                            ),
                          )}
                          {configuration.truncated ? (
                            <div className="text-[11px] text-orange-200/70">
                              {tr(
                                "Additional creatives are hidden from this compact preview.",
                              )}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ) : null}
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
                    {isApproved ? (
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={() => void toggleLivePlan(item)}
                        className="inline-flex items-center justify-center gap-2 rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-medium text-electric-200 disabled:opacity-40"
                      >
                        <ShieldCheck className="h-3.5 w-3.5" />
                        {livePanelId === item.id
                          ? tr("Hide live-plan preparation")
                          : tr("Open live-plan preparation")}
                      </button>
                    ) : null}
                  </div>
                </div>

                {isApproved && livePanelId === item.id ? (
                  <div className="mt-4 rounded-xl border border-electric-500/15 bg-electric-500/[0.03] p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <div className="text-xs font-semibold text-electric-200">
                          {tr("Fail-closed live-plan preparation")}
                        </div>
                        <div className="mt-1 text-[11px] leading-5 text-white/35">
                          {tr(
                            "This prepares and validates an internal plan only. It does not call Meta, authorize launch, or spend money.",
                          )}
                        </div>
                      </div>
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={() => void loadLiveSources()}
                        className="rounded-lg border border-white/10 px-3 py-2 text-[11px] text-white/55 disabled:opacity-40"
                      >
                        {tr("Refresh live-plan sources")}
                      </button>
                    </div>

                    <div className="mt-4 grid gap-3 lg:grid-cols-2">
                      <label className="text-xs text-white/45">
                        {tr("Controlled live-spend pilot")}
                        <select
                          value={planInput.pilotId}
                          onChange={(event) =>
                            updatePlanInput(item.id, {
                              pilotId: event.target.value,
                            })
                          }
                          className="mt-1 w-full rounded-lg border border-white/10 bg-ink-950 px-3 py-2 text-xs text-white"
                        >
                          <option value="">{tr("Select pilot")}</option>
                          {candidatePilots.map((pilot) => (
                            <option key={pilot.id} value={pilot.id}>
                              {pilot.currency || "—"} · {pilot.status} ·{" "}
                              {pilot.id.slice(0, 8)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="text-xs text-white/45">
                        {tr("Meta Page identity")}
                        <select
                          value={planInput.pageRef}
                          onChange={(event) =>
                            updatePlanInput(item.id, {
                              pageRef: event.target.value,
                            })
                          }
                          className="mt-1 w-full rounded-lg border border-white/10 bg-ink-950 px-3 py-2 text-xs text-white"
                        >
                          <option value="">{tr("Select Meta Page")}</option>
                          {metaPages.map((page) => (
                            <option key={page.page_ref} value={page.page_ref}>
                              {page.name} · {page.tasks.join(", ")}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    {liveDataLoaded && candidatePilots.length === 0 ? (
                      <div className="mt-3 text-xs text-orange-200/75">
                        {tr(
                          "No matching live-spend pilot exists for this organization.",
                        )}
                      </div>
                    ) : null}
                    {liveDataLoaded && metaPages.length === 0 ? (
                      <div className="mt-3 text-xs text-orange-200/75">
                        {tr(
                          "No Meta Page with advertising access is available to the current credential.",
                        )}
                      </div>
                    ) : null}

                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={busyId !== null || !planInput.pilotId}
                        onClick={() => void evaluatePlan(item)}
                        className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white/65 disabled:opacity-40"
                      >
                        {tr("Evaluate live plan")}
                      </button>
                      <button
                        type="button"
                        disabled={
                          busyId !== null ||
                          !planInput.pilotId ||
                          !planInput.pageRef
                        }
                        onClick={() => void preparePlan(item)}
                        className="rounded-lg bg-electric-500/15 px-3 py-2 text-xs font-medium text-electric-200 disabled:opacity-40"
                      >
                        {tr("Prepare live-plan digest")}
                      </button>
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={() => void validatePlan(item)}
                        className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/55 disabled:opacity-40"
                      >
                        {tr("Validate stored plan")}
                      </button>
                    </div>

                    {planResult ? (
                      <div className="mt-4 rounded-lg border border-white/[0.06] bg-black/10 p-3 text-xs">
                        <div className="flex flex-wrap gap-2">
                          {"plan_compilable" in planResult ? (
                            <span
                              className={
                                planResult.plan_compilable
                                  ? "text-green-300"
                                  : "text-orange-300"
                              }
                            >
                              {tr("Plan compilable")}:{" "}
                              {String(planResult.plan_compilable)}
                            </span>
                          ) : null}
                          {planResult.plan_valid !== undefined ? (
                            <span
                              className={
                                planResult.plan_valid
                                  ? "text-green-300"
                                  : "text-red-300"
                              }
                            >
                              {tr("Stored digest valid")}:{" "}
                              {String(planResult.plan_valid)}
                            </span>
                          ) : null}
                          <span className="text-white/40">
                            {tr("Provider call")}:{" "}
                            {String(planResult.provider_call_executed)}
                          </span>
                          <span className="text-white/40">
                            {tr("Spend")}: {String(planResult.spend_executed)}
                          </span>
                        </div>
                        {planResult.blocked_reasons?.length ? (
                          <div className="mt-2 text-orange-200/70">
                            {tr("Blocked reasons")}:{" "}
                            {planResult.blocked_reasons
                              .map(technicalText)
                              .join(", ")}
                          </div>
                        ) : null}
                        <div className="mt-2 text-[11px] text-white/30">
                          {tr(
                            "Runtime authorization and a separate Owner launch decision remain mandatory even after a valid plan is prepared.",
                          )}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
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
