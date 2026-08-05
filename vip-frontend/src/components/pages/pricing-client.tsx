"use client";

import { ArrowUpRight, Check, Sparkles } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";

export function PricingClient() {
  const { configuration, locale, text, href } = usePortalExperience();
  const pricing = configuration?.pricing;
  const periodIds = useMemo(() => {
    const values = new Set<string>();
    pricing?.plans.forEach((plan) => plan.periods.filter((period) => period.enabled).forEach((period) => values.add(period.id)));
    return Array.from(values);
  }, [pricing]);
  const [periodId, setPeriodId] = useState<string | null>(null);
  const selectedPeriod = periodId || pricing?.default_period || periodIds[0] || "monthly";
  if (pricing && !pricing.enabled) {
    return <section className="section-pad"><div className="page-shell max-w-3xl text-center"><h1 className="section-title">{locale === "ar" ? "الأسعار غير متاحة حاليًا" : "Pricing is not currently available"}</h1></div></section>;
  }
  const plans = (pricing?.plans || []).filter((plan) => plan.enabled).sort((a, b) => a.order - b.order);
  return (
    <>
      <section className="section-pad relative overflow-hidden border-b border-white/[0.07]">
        <div className="pointer-events-none absolute inset-0 grid-surface opacity-50" />
        <div className="page-shell relative max-w-5xl text-center">
          <span className="eyebrow"><Sparkles className="h-3.5 w-3.5" />{locale === "ar" ? "الاشتراكات" : "Subscriptions"}</span>
          <h1 className="section-title mx-auto mt-7 max-w-4xl text-4xl sm:text-6xl">{text(pricing?.heading, locale === "ar" ? "الخطط والأسعار" : "Plans and pricing")}</h1>
          <p className="section-copy mx-auto mt-6 max-w-3xl">{text(pricing?.description)}</p>
          {periodIds.length > 1 && <div className="mt-8 inline-flex rounded-xl border border-white/10 bg-white/[0.04] p-1">{periodIds.map((id) => { const sample=pricing?.plans.flatMap((plan)=>plan.periods).find((period)=>period.id===id); return <button key={id} type="button" onClick={()=>setPeriodId(id)} className={`rounded-lg px-4 py-2 text-sm ${selectedPeriod===id ? "bg-white text-ink-950" : "text-white/60"}`}>{text(sample?.label,id)}</button>; })}</div>}
        </div>
      </section>
      <section className="section-pad"><div className="page-shell"><div className="grid gap-5 lg:grid-cols-3">{plans.map((plan)=>{
        const period=plan.periods.find((item)=>item.enabled&&item.id===selectedPeriod) || plan.periods.find((item)=>item.enabled);
        const formatted=period?.price == null ? (locale === "ar" ? "تواصل معنا" : "Contact us") : new Intl.NumberFormat(locale,{style:"currency",currency:period.currency,maximumFractionDigits:2}).format(period.price);
        return <article key={plan.id} className={`relative rounded-3xl border p-7 sm:p-8 ${plan.featured ? "border-electric-300/35 bg-electric-400/[0.08] shadow-glow" : "border-white/[0.08] bg-white/[0.025]"}`}>
          {text(plan.badge) && <span className="absolute end-5 top-5 rounded-full border border-electric-300/20 bg-electric-400/10 px-3 py-1 text-[11px] font-bold text-electric-100">{text(plan.badge)}</span>}
          <h2 className="text-2xl font-semibold">{text(plan.name)}</h2><p className="mt-3 min-h-14 text-sm leading-7 text-white/50">{text(plan.description)}</p>
          <div className="mt-7"><span className="text-4xl font-bold">{formatted}</span>{period?.price != null && <span className="ms-2 text-xs text-white/35">{text(period.label)}</span>}</div>
          {period?.compare_at_price != null && <p className="mt-2 text-sm text-white/35 line-through">{new Intl.NumberFormat(locale,{style:"currency",currency:period.currency}).format(period.compare_at_price)}</p>}
          <ul className="mt-7 space-y-3">{plan.features.map((feature,index)=><li key={index} className="flex items-start gap-3 text-sm text-white/60"><Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />{text(feature)}</li>)}</ul>
          <Link href={href(plan.cta_url)} className="portal-primary-button mt-8 inline-flex h-12 w-full items-center justify-center gap-2 px-5 text-sm font-bold text-white">{text(plan.cta_label)}<ArrowUpRight className="h-4 w-4" /></Link>
        </article>;
      })}</div>{!plans.length && <div className="rounded-3xl border border-dashed border-white/10 p-12 text-center text-white/45">{locale === "ar" ? "لم ينشر المالك أي خطة بعد." : "The owner has not published any plans yet."}</div>}
      {pricing?.show_tax_note && <p className="mt-8 text-center text-xs text-white/35">{text(pricing.tax_note)}</p>}</div></section>
      {!!pricing?.faq.length && <section className="section-pad border-t border-white/[0.07]"><div className="page-shell max-w-4xl"><h2 className="section-title text-center">{locale === "ar" ? "الأسئلة الشائعة" : "Frequently asked questions"}</h2><div className="mt-8 space-y-3">{pricing.faq.map((item,index)=><details key={index} className="glass-panel rounded-2xl p-5"><summary className="cursor-pointer font-semibold">{text(item.question)}</summary><p className="mt-4 text-sm leading-7 text-white/50">{text(item.answer)}</p></details>)}</div></div></section>}
    </>
  );
}
