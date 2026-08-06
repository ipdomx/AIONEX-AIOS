"use client";

import { ArrowUpRight, Check, LoaderCircle, Sparkles } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";
import { getPublicBillingCatalog } from "@/lib/api";
import type { BillingCatalog } from "@/types";

function localized(
  value: Record<string, string> | undefined,
  locale: string,
  fallback = "",
): string {
  return value?.[locale] || value?.en || value?.ar || fallback;
}

export function PricingClient() {
  const { configuration, locale, text, href } = usePortalExperience();
  const { isAuthenticated } = useAuth();
  const portalPricing = configuration?.pricing;
  const [catalog, setCatalog] = useState<BillingCatalog | null>(null);
  const [periodId, setPeriodId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCatalog(await getPublicBillingCatalog());
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : locale === "ar"
            ? "تعذر تحميل الأسعار."
            : "Pricing could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    void load();
  }, [load]);

  const periodIds = useMemo(() => {
    const values = new Set<string>();
    catalog?.plans.forEach((plan) =>
      plan.periods
        .filter((period) => period.enabled)
        .forEach((period) => values.add(period.id)),
    );
    return Array.from(values);
  }, [catalog]);

  const selectedPeriod =
    periodId || catalog?.default_period || periodIds[0] || "monthly";

  if (loading) {
    return (
      <section className="section-pad">
        <div className="page-shell flex min-h-[45vh] items-center justify-center">
          <LoaderCircle className="h-8 w-8 animate-spin text-electric-200" />
        </div>
      </section>
    );
  }

  if (!catalog || !catalog.enabled) {
    return (
      <section className="section-pad">
        <div className="page-shell max-w-3xl text-center">
          <h1 className="section-title">
            {locale === "ar"
              ? "الأسعار غير متاحة حاليًا"
              : "Pricing is not currently available"}
          </h1>
          {error && <p className="mt-5 text-sm text-red-200">{error}</p>}
        </div>
      </section>
    );
  }

  const plans = catalog.plans
    .filter((plan) => plan.enabled)
    .sort((left, right) => left.order - right.order);

  return (
    <>
      <section className="section-pad relative overflow-hidden border-b border-white/[0.07]">
        <div className="pointer-events-none absolute inset-0 grid-surface opacity-50" />
        <div className="page-shell relative max-w-5xl text-center">
          <span className="eyebrow">
            <Sparkles className="h-3.5 w-3.5" />
            {locale === "ar" ? "الاشتراكات" : "Subscriptions"}
          </span>
          <h1 className="section-title mx-auto mt-7 max-w-4xl text-4xl sm:text-6xl">
            {localized(
              catalog.heading,
              locale,
              text(
                portalPricing?.heading,
                locale === "ar" ? "الخطط والأسعار" : "Plans and pricing",
              ),
            )}
          </h1>
          <p className="section-copy mx-auto mt-6 max-w-3xl">
            {localized(
              catalog.description,
              locale,
              text(portalPricing?.description),
            )}
          </p>
          {periodIds.length > 1 && (
            <div className="mt-8 inline-flex flex-wrap justify-center rounded-xl border border-white/10 bg-white/[0.04] p-1">
              {periodIds.map((id) => {
                const sample = catalog.plans
                  .flatMap((plan) => plan.periods)
                  .find((period) => period.id === id);
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setPeriodId(id)}
                    className={`rounded-lg px-4 py-2 text-sm ${
                      selectedPeriod === id
                        ? "bg-white text-ink-950"
                        : "text-white/60"
                    }`}
                  >
                    {localized(sample?.label, locale, id)}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </section>

      <section className="section-pad">
        <div className="page-shell">
          {error && (
            <p className="mb-6 rounded-2xl border border-red-400/20 bg-red-500/10 px-5 py-4 text-center text-sm text-red-100">
              {error}
            </p>
          )}
          <div className="grid gap-5 lg:grid-cols-3">
            {plans.map((plan) => {
              const period =
                plan.periods.find(
                  (item) => item.enabled && item.id === selectedPeriod,
                ) || plan.periods.find((item) => item.enabled);
              const formatted =
                period?.amount_minor == null
                  ? locale === "ar"
                    ? "تواصل معنا"
                    : "Contact us"
                  : new Intl.NumberFormat(locale, {
                      style: "currency",
                      currency: period.currency,
                      maximumFractionDigits: 2,
                    }).format(period.amount_minor / 100);
              const cta =
                isAuthenticated && period?.checkout_available
                  ? `/${locale}/billing?plan=${encodeURIComponent(plan.code)}&period=${encodeURIComponent(period.id)}`
                  : href(
                      portalPricing?.plans.find((item) => item.id === plan.code)
                        ?.cta_url || `/${locale}/register`,
                    );
              return (
                <article
                  key={plan.code}
                  className={`relative rounded-3xl border p-7 sm:p-8 ${
                    plan.featured
                      ? "border-electric-300/35 bg-electric-400/[0.08] shadow-glow"
                      : "border-white/[0.08] bg-white/[0.025]"
                  }`}
                >
                  <h2 className="text-2xl font-semibold">
                    {localized(plan.name, locale, plan.code)}
                  </h2>
                  <p className="mt-3 min-h-14 text-sm leading-7 text-white/50">
                    {localized(plan.description, locale)}
                  </p>
                  <div className="mt-7">
                    <span className="text-4xl font-bold">{formatted}</span>
                    {period?.amount_minor != null && (
                      <span className="ms-2 text-xs text-white/35">
                        {localized(period.label, locale, period.id)}
                      </span>
                    )}
                  </div>
                  {period?.compare_at_minor != null && (
                    <p className="mt-2 text-sm text-white/35 line-through">
                      {new Intl.NumberFormat(locale, {
                        style: "currency",
                        currency: period.currency,
                      }).format(period.compare_at_minor / 100)}
                    </p>
                  )}
                  <ul className="mt-7 space-y-3">
                    {plan.features.map((feature, index) => (
                      <li
                        key={index}
                        className="flex items-start gap-3 text-sm text-white/60"
                      >
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                        {localized(feature, locale)}
                      </li>
                    ))}
                  </ul>
                  <Link
                    href={cta}
                    className="portal-primary-button mt-8 inline-flex h-12 w-full items-center justify-center gap-2 px-5 text-sm font-bold text-white"
                  >
                    {isAuthenticated && period?.checkout_available
                      ? locale === "ar"
                        ? "اختيار وبدء الدفع"
                        : "Choose and pay"
                      : localized(
                          plan.cta_label,
                          locale,
                          locale === "ar" ? "اختر الخطة" : "Choose plan",
                        )}
                    <ArrowUpRight className="h-4 w-4" />
                  </Link>
                </article>
              );
            })}
          </div>
          {!plans.length && (
            <div className="rounded-3xl border border-dashed border-white/10 p-12 text-center text-white/45">
              {locale === "ar"
                ? "لم ينشر المالك أي خطة بعد."
                : "The owner has not published any plans yet."}
            </div>
          )}
          {catalog.show_tax_note && (
            <p className="mt-8 text-center text-xs text-white/35">
              {localized(catalog.tax_note, locale)}
            </p>
          )}
        </div>
      </section>

      {!!catalog.faq.length && (
        <section className="section-pad border-t border-white/[0.07]">
          <div className="page-shell max-w-4xl">
            <h2 className="section-title text-center">
              {locale === "ar"
                ? "الأسئلة الشائعة"
                : "Frequently asked questions"}
            </h2>
            <div className="mt-8 space-y-3">
              {catalog.faq.map((item, index) => (
                <details key={index} className="glass-panel rounded-2xl p-5">
                  <summary className="cursor-pointer font-semibold">
                    {localized(item.question, locale)}
                  </summary>
                  <p className="mt-4 text-sm leading-7 text-white/50">
                    {localized(item.answer, locale)}
                  </p>
                </details>
              ))}
            </div>
          </div>
        </section>
      )}
    </>
  );
}
